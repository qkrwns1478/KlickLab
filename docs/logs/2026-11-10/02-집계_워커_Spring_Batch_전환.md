# 집계 워커 Spring Batch 전환 (klicklab-workers → backend `aggregation` 패키지)

## 요청

[Eatventory/klicklab-workers](https://github.com/Eatventory/klicklab-workers)(집계 전용 테이블에 INSERT 하는 Node.js 스크립트)를 Spring Batch로 변환

| 구분 | 기존 | 신규 |
| --- | --- | --- |
| 실행 | `node index.js`(node-cron) + `insert??.js` 12개 | backend 앱 안의 Spring Batch Job 4개 |
| DB | ClickHouse (`INSERT … SELECT`) | PostgreSQL (`DELETE` + `INSERT … SELECT`) |
| 수동 실행 | `node insertMM.js 2025-07-12T14:30`, `node test.js 시작일 종료일` | `./gradlew bootRun --args="--aggregate=… --at=…"` |

## 구성

- 별도 앱이 아니라 `backend`에 `com.klicklab.aggregation` 패키지로 추가 (배포 없이 로컬에서만 실행하므로 DataSource·Flyway·타임존·테스트 환경을 공유)
- Spring Boot 4.1.2 / Spring Batch 6.0.6 (`spring-boot-starter-batch-jdbc`), JobRepository 메타데이터는 같은 PostgreSQL에 저장

| 파일 | 내용 |
| --- | --- |
| `Granularity` | 단위(minutes 10분 / hourly 1시간 / daily 1일 / weekly 7일), 구간 정렬, 직전 구간, 스케줄 시점 |
| `AggregationTarget` | 집계 테이블 5종(metrics, click_summary, top_elements, user_distribution, page_stats)과 원천(events 또는 하위 단위) |
| `AggregationSql` | 기존 쿼리 20개를 PostgreSQL로 이식 |
| `AggregationJobConfig` | 단위별 Job 4개 × 테이블별 Tasklet Step 5개 |
| `AggregationTasklet` | 구간 하나를 DELETE 후 INSERT (Step 트랜잭션 + 테이블별 advisory lock) |
| `AggregationJobLauncher` | 구간 실행, 직전 구간 실행, 기간 백필(기존 `test.js`) |
| `AggregationScheduler` | 기존 `index.js`: 매 10분 minutes, 정각 hourly, 매일 00:10 daily, 매주 월요일 00:30 weekly (순서대로, 실패 시 이후 단위 중단) |
| `AggregationCommand` | `--aggregate=minutes\|hourly\|daily\|weekly\|backfill` 명령행 실행 (웹 서버·스케줄러 없이 실행 후 종료) |

집계 원천은 기존과 같음

```
events ─▶ minutes_* ─▶ hourly_* ─▶ daily_metrics / daily_page_stats ─▶ weekly_*
events ───────────────────────────▶ daily_click_summary / top_elements / user_distribution ─┘
```

- Chunk(Reader/Writer) 대신 Tasklet 사용: 모든 집계가 DB 안의 `INSERT … SELECT`로 끝나므로 행을 JVM으로 읽어올 필요가 없음
- 실행마다 `requestedAt` 파라미터를 붙여 새 JobInstance로 실행 → 같은 구간을 다시 실행할 수 있음

### DB 마이그레이션
- `V2__spring_batch_metadata.sql`: spring-batch-core 6.0.6 jar의 `schema-postgresql.sql` 원본 (`spring.batch.jdbc.initialize-schema: never`)
- `V3__aggregation_tables.sql`: 집계 테이블 20개 (`{minutes,hourly,daily,weekly}_{metrics,click_summary,top_elements,user_distribution,page_stats}`), 신규 방문자 판별용 인덱스 `events (sdk_key, client_id, timestamp)`
  - 컬럼명은 기존 ClickHouse 테이블과 동일 (`date_time` / `date`, `target_text`는 PostgreSQL `events.element` 사용)
  - ClickHouse `Nested(next_pages.to, next_pages.count)` → `next_pages JSONB` (`[{"to": "/cart", "count": 3}, …]`)

### 기타 변경
- `application.yml`: `spring.batch.job.enabled: false` (기동 시 Job 자동 실행 방지), `klicklab.aggregation.enabled` (`AGGREGATION_ENABLED`, 기본 true)
- `KlickLabApplication.main`: `--aggregate=` 옵션이 있으면 `AggregationCommand.execute`로 분기
- `SecurityConfig.securityFilterChain`: `@ConditionalOnWebApplication` (웹 서버 없는 명령 실행 시 `HttpSecurity` 빈이 없어 기동 실패하던 문제)
- `README.md`: 집계 Job 실행 방법 추가

## 기존 워커와 다르게 동작하는 부분 (버그 수정)

| 기존 | 변경 |
| --- | --- |
| `insertHM`/`DM`/`WM`이 컬럼명 없이 `INSERT … SELECT` 하면서 `existing_visitors`, `new_visitors` 순서로 SELECT (`insertMM`은 반대 순서) → 상위 단위에서 신규/기존 방문자가 뒤바뀜 | 모든 INSERT에 컬럼 목록 명시 |
| 상위 단위 `page_stats`가 `any(next_pages)`로 하위 구간 중 임의의 하나만 사용 | 다음 페이지별 이동 횟수를 합산 |
| `minutes_page_stats`의 `groupArray(next_page)`가 이벤트마다 같은 페이지를 중복 추가하고, `NULL`(이탈)은 건너뛰어 `to`/`count` 배열 길이가 어긋남 | 다음 페이지별 1건 + 횟수, 횟수 내림차순 |
| `insertMU`/`insertDU`가 `BETWEEN 시작 AND 끝`을 사용해 경계 시각 이벤트가 두 구간에 중복 집계 | 모든 구간을 `[시작, 끝)`으로 통일 |
| `insertDU`의 기본 날짜를 UTC(`toISOString`)로 계산 → 00:10 KST 실행 시 이틀 전 날짜를 집계 | 서비스 타임존(Asia/Seoul) 기준 어제 |
| 재실행 시 행이 중복 추가 (`test.js`만 사전 DELETE) | 모든 실행이 구간 DELETE 후 INSERT (멱등) |
| 스크립트가 오류를 잡고 정상 종료해 다음 단위가 계속 실행됨 | Step 실패 → Job FAILED, 스케줄러는 이후 단위 중단 |
| `insertMU` Top 3 쿼리에 같은 컬럼이 중복으로 들어간 SELECT | 정리, 동점은 요소 이름순 |

- 추가: 백필(`test.js` 대응)은 아직 끝나지 않은 구간을 건너뜀, `--at` 시각은 구간 시작으로 내림 (예: `14:37` → `14:30`)
- 유지: 상위 단위의 평균(세션 시간, 페이지 체류 시간)은 하위 구간 평균의 평균, 순 사용자 수(`visitors`, `total_users`, `user_count`)는 하위 구간 합산 (기존과 같은 근사치), `page_views`는 `page_path`가 있는 모든 이벤트 수

## 검증
- `GranularityTest` (4개): 구간 정렬/직전 구간, 기존 `index.js`와 같은 스케줄 시점, SQL 대상 테이블, 기존 인자 형식 파싱
- `AggregationJobIntegrationTest` (8개, Testcontainers): 신규/기존 방문자와 세션 시간, 단위별 합산, 세그먼트별 클릭 요약, Top 3 순위, 연령대/기기 분포, `next_pages` 합산, 재실행 시 결과 동일 및 Batch 메타데이터 기록, 하루 백필(Job 169회)
- `./gradlew clean build`: 기존 테스트 포함 30개 전체 통과
- 로컬 DB(5433)에서 `--aggregate=backfill`, `--aggregate=hourly --at=…` 실행 → 종료 코드 0, 결과 확인 / 잘못된 날짜 형식은 종료 코드 1. 확인용으로 넣은 이벤트·집계 행·Batch 이력은 삭제함

## 참고
- 현재 API는 이 집계 테이블을 조회하지 않음 (Spring Boot 마이그레이션 때 기존 `stats.js`, `trafficUtils.js`의 조회를 `events`/`agg_*`로 대체했음). 대시보드에 쓰려면 조회 쪽 전환이 별도로 필요
- 앱이 꺼져 있던 동안의 구간은 자동으로 채우지 않음 → `--aggregate=backfill`로 보충
- 하루 백필은 Job 169회(10분 144 + 1시간 24 + 1일 1)를 실행하며 데이터가 적을 때 약 10~20초 소요
