# LLM 분석 에이전트 Phase 0: 프로젝트 골격 및 V4 마이그레이션

## 요청

`docs/plans/01-text_to_sql_LLM_분석_에이전트_구현_계획.md`의 Phase 0 구현.

## 작업 내용

### 1. `V4__agent.sql` (backend Flyway)

- `agent_runs`, `agent_steps`: 실행 로그. `difficulty`/`status`/`feedback`에 CHECK 제약.
- `agent_knowledge`: RAG 저장소. `vector(1024)`(bge-m3 기준) + HNSW(cosine) 인덱스, `pg_trgm` GIN 인덱스(하이브리드 검색용), `(kind, name)` 유일 제약.
- 롤을 계획(단일 `klicklab_agent`)에서 **두 개로 분리**했다.
  - `klicklab_agent_ro`: LLM이 만든 SQL 실행 전용. 화이트리스트 33개 테이블(`events`, `conversion_events`, `agg_*` 11개, `minutes/hourly/daily/weekly_*` 20개)에 SELECT만 부여.
  - `klicklab_agent`: `agent_runs`/`agent_steps`/`agent_knowledge` 읽기·쓰기 전용. 원천/집계 테이블 접근 불가.
  - 이유: 로그 적재에는 쓰기 권한이 필요한데, SQL 실행 연결이 쓰기 권한을 가지면 읽기 전용 방어가 약해진다.
- RLS: 화이트리스트 테이블에 `sdk_key = current_setting('app.sdk_key', true)` 정책(`klicklab_agent_ro` 대상). 설정이 없으면 NULL이라 0행. 테이블 소유자(Spring 앱 계정)는 RLS를 우회하므로 기존 동작은 그대로다.
- 두 롤은 `NOLOGIN`으로 생성하고 비밀번호는 마이그레이션에 두지 않는다. 로컬 설정 방법은 `agent/.env.example`에 적었다.
- `users`, `event_rules`, `event_button`, `rollup_runs`, `BATCH_*`는 허용 목록에서 제외.

### 2. `agent/` 프로젝트 골격

- `pyproject.toml`(uv, Python 3.12): FastAPI, uvicorn, pydantic-settings, psycopg, pyjwt / dev: pytest, httpx, ruff
- `app/config.py`: 환경변수 설정, 읽기/쓰기 DSN 분리
- `app/auth.py`: Spring 발급 JWT(HS256) 검증, `sdk_key` 클레임 추출
- `app/main.py`: `GET /agent/health`, `GET /agent/me`(인증 확인용), CORS
- `tests/test_app.py`: 헬스체크, 토큰 없음/서명 불일치/`sdk_key` 없음 거부, 정상 토큰
- ruff: FastAPI `Depends` 기본값 패턴(B008)은 `extend-immutable-calls`로 허용

## 검증

- 로컬 PostgreSQL에서 V4를 트랜잭션 안에서 실행 후 롤백하며 확인: 데모 `sdk_key`로는 `events` 265,372행 조회, 다른 `sdk_key`로는 0행, `users` 조회는 권한 거부.
- `AggregationJobIntegrationTest`, `GranularityTest` 통과 (Testcontainers 빈 DB에 V1~V4 적용 성공).
- `agent/`: `ruff check`, `ruff format --check`, `pytest` 5건 통과.

## 참고

- 로컬 개발 DB(`klicklab-postgres`)에는 V4가 아직 적용되지 않았다. 백엔드를 한 번 기동하면 Flyway가 적용한다.
- Gradle 실행 시 기본 JDK가 8이라 `JAVA_HOME`을 `~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2`로 지정해 실행했다.
- 임베딩 차원(1024)은 Phase 3에서 임베딩 모델 확정 시 달라지면 마이그레이션(V5)으로 변경해야 한다.
