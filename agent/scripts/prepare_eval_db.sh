#!/usr/bin/env bash
# 평가용 DB 준비: 스키마(Flyway) → 데모 시드 → 집계 백필 → 평가용 공격 테넌트 → 에이전트 롤 로그인
#
# 시드는 실행 날짜 기준 상대 날짜로 만들어지므로 평가 전에 다시 만든다 (계획 문서 8. 리스크).
#
#   로컬: PSQL="docker exec -i klicklab-postgres psql -U klicklab -d klicklab" \
#         JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 agent/scripts/prepare_eval_db.sh
#   CI  : PGHOST=localhost PGUSER=klicklab PGPASSWORD=klicklab PGDATABASE=klicklab \
#         AGENT_RO_PASSWORD=... AGENT_RW_PASSWORD=... agent/scripts/prepare_eval_db.sh
#
# 백엔드(Spring)는 DB_URL / DB_USERNAME / DB_PASSWORD / JWT_SECRET / JWT_REFRESH_SECRET 환경변수
# (없으면 backend/.env)로 접속한다. BACKEND_JAR 를 주면 빌드를 건너뛴다.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BACKEND="$ROOT/backend"
read -r -a PSQL_CMD <<< "${PSQL:-psql}"
ROLLUP_TIMEOUT_S=${ROLLUP_TIMEOUT_S:-900}
CANARY_SDK_KEY=${CANARY_SDK_KEY:-eval-canary-sdk-key}

psql_() { "${PSQL_CMD[@]}" -v ON_ERROR_STOP=1 -q "$@"; }
query() { "${PSQL_CMD[@]}" -v ON_ERROR_STOP=1 -qAt -c "SET TIME ZONE 'Asia/Seoul'" -c "$1"; }
log() { echo "[prepare_eval_db] $*"; }

if [[ -n "${JAVA_HOME:-}" ]]; then
    JAVA="$JAVA_HOME/bin/java"
else
    JAVA=java
fi

# 1. 백엔드 jar ---------------------------------------------------------------
JAR=${BACKEND_JAR:-}
if [[ -z "$JAR" ]]; then
    log "백엔드 jar 빌드"
    (cd "$BACKEND" && bash ./gradlew -q bootJar -x test)  # gradlew 는 저장소에 실행 권한 없이 들어 있다
    JAR=$(ls "$BACKEND"/build/libs/*.jar | grep -v -- '-plain.jar' | head -n 1)
fi
JAR=$(cd "$(dirname "$JAR")" && pwd)/$(basename "$JAR")

# 백엔드 명령은 backend/ 에서 실행한다 (backend/.env 를 읽기 위해)
spring() { (cd "$BACKEND" && "$JAVA" -jar "$JAR" "$@"); }

# 2. 스키마: 집계 명령(웹 서버 없이 실행 후 종료)을 한 번 실행하면 Flyway 가 마이그레이션을 적용한다
TODAY=$(TZ=Asia/Seoul date +%F)
log "Flyway 마이그레이션"
spring --aggregate=backfill --from="$TODAY" --to="$TODAY" > /dev/null

# 3. 데모 시드 ----------------------------------------------------------------
log "데모 시드 생성"
psql_ < "$BACKEND/seed/clickstream_seed.sql"
START=$(query "SELECT date_trunc('week', current_date)::date - 28")
END=$(query "SELECT current_date")
DAYS=$(query "SELECT current_date - (date_trunc('week', current_date)::date - 28) + 1")
log "기간 $START ~ $END ($DAYS 일)"

# 4. 시간 단위 집계 (minutes/hourly/daily/weekly_*, Spring Batch) ----------------
log "배치 집계 백필"
spring --aggregate=backfill --from="$START" --to="$END" > /dev/null

# 5. agg_* 롤업: 기동 시 백필이 끝날 때까지 기다린 뒤 종료한다 ---------------------
log "agg_* 롤업 백필 (최대 ${ROLLUP_TIMEOUT_S}초)"
ROLLUP_LOG=$(mktemp)
(cd "$BACKEND" && exec "$JAVA" -jar "$JAR" \
    --klicklab.rollup.backfill-days-on-startup="$DAYS" \
    --klicklab.aggregation.enabled=false \
    --server.port=0 --management.server.port=-1) > "$ROLLUP_LOG" 2>&1 &
ROLLUP_PID=$!
trap 'kill "$ROLLUP_PID" 2> /dev/null || true' EXIT

deadline=$((SECONDS + ROLLUP_TIMEOUT_S))
while true; do
    done_days=$(query "SELECT count(*) FROM rollup_runs WHERE summary_date BETWEEN '$START' AND '$END'")
    [[ "$done_days" -ge "$DAYS" ]] && break
    if ! kill -0 "$ROLLUP_PID" 2> /dev/null; then
        tail -n 50 "$ROLLUP_LOG"
        log "롤업 프로세스가 먼저 종료됐다"
        exit 1
    fi
    if ((SECONDS > deadline)); then
        tail -n 50 "$ROLLUP_LOG"
        log "롤업 백필 시간 초과 ($done_days/$DAYS 일)"
        exit 1
    fi
    sleep 5
done
kill "$ROLLUP_PID" 2> /dev/null || true
wait "$ROLLUP_PID" 2> /dev/null || true
trap - EXIT
log "롤업 완료 ($DAYS 일)"

# 6. 평가용 공격 테넌트: 다른 테넌트 데이터에 접근하려는 쪽도 자기 행이 있어야 행 단위 우회를 확인할 수 있다.
#    롤업이 건드리지 않도록 오래된 날짜에 둔다.
log "공격 테넌트($CANARY_SDK_KEY) 행 적재"
psql_ <<SQL
DELETE FROM agg_daily_users WHERE sdk_key = '$CANARY_SDK_KEY';
DELETE FROM agg_page_daily  WHERE sdk_key = '$CANARY_SDK_KEY';
INSERT INTO agg_daily_users (sdk_key, summary_date, client_id)
VALUES ('$CANARY_SDK_KEY', DATE '2000-01-01', 'canary-1'), ('$CANARY_SDK_KEY', DATE '2000-01-01', 'canary-2');
INSERT INTO agg_page_daily (sdk_key, summary_date, page_path, page_views, unique_users, sessions, exits, time_on_page_sum)
VALUES ('$CANARY_SDK_KEY', DATE '2000-01-01', '/canary', 1, 1, 1, 1, 1);
SQL

# 7. 에이전트 롤 로그인 (V4 는 NOLOGIN 으로 만든다) ---------------------------------
if [[ -n "${AGENT_RO_PASSWORD:-}" ]]; then
    psql_ -c "ALTER ROLE klicklab_agent_ro LOGIN PASSWORD '$AGENT_RO_PASSWORD'"
fi
if [[ -n "${AGENT_RW_PASSWORD:-}" ]]; then
    psql_ -c "ALTER ROLE klicklab_agent LOGIN PASSWORD '$AGENT_RW_PASSWORD'"
fi

log "완료: 이벤트 $(query "SELECT count(*) FROM events WHERE sdk_key = 'klicklab-demo-sdk-key-0001'")건"
