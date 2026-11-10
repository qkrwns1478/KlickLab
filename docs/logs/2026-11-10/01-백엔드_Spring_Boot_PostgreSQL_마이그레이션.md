# 백엔드 기술 스택 마이그레이션 (Spring Boot + PostgreSQL/pgvector)

- 작업일: 2026-11-10
- 브랜치: `dev`
- 상태: 작업 트리에 반영됨 (커밋 전)

## 요청

| 구분 | 기존 | 신규 |
| --- | --- | --- |
| 서버 | Node.js + Express | Spring Boot (Gradle Groovy) |
| 데이터베이스 | ClickHouse + PostgreSQL | PostgreSQL 단독 + pgvector |

## 최종 구성

- Spring Boot 4.1.2, Java 21, Gradle 9.8.2 (wrapper 포함)
- PostgreSQL 17 (`pgvector/pgvector:pg17` 이미지), Flyway 마이그레이션
- 인증: Spring Security + JJWT 0.13.0 (HS256), BCrypt (cost 10)
- 메트릭: Actuator + Micrometer Prometheus (`:9091/metrics`)
- API는 `:4000`, 기존 URL과 JSON 응답 형태를 유지하여 프론트엔드는 수정하지 않음

## 작업 내용

### 1. 기존 코드 분석
- `backend/`의 Express 라우트 14개, 서비스, 유틸 (약 6,500줄)과 ClickHouse 쿼리를 모두 확인
- 사용 중인 테이블: `events`, `agg_*`/`flat_*` (user_session, page_content, event, traffic_marketing, realtime), `*_metrics`, `*_user_distribution`, `funnel_links_daily`, `first_pages_daily`, `sankey_paths_daily`, `event_rules`, `event_button`, `conversion_events`, `users`
- 프론트엔드가 사용하는 응답 필드(`age_group`, `summary_date`, `url_path`/`event_path`, ISO `baseTime` 등)를 확인

### 2. Node.js 백엔드 제거
- `git rm`으로 `index.js`, `routes/`, `services/`, `utils/`, `middlewares/`, `src/`, `data/`, `package*.json` 삭제 (git 이력에 남아 있음)

### 3. Spring Boot 프로젝트 생성 (`backend/`)

| 패키지 | 내용 |
| --- | --- |
| `auth` | 로그인/재발급/로그아웃/회원가입, JWT 발급·검증 필터 |
| `config` | `SecurityConfig`(CORS, 인증 규칙), `KlickLabProperties` |
| `common` | `Db`(JDBC 래퍼), `DateRange`, `AppClock`, 예외 처리, 요청 로깅 |
| `overview`, `stats`, `users`, `traffic`, `engagement`, `acquisition`, `funnel`, `report` | 분석 API |
| `settings`, `rules`(이벤트 규칙·버튼·SDK·전환 이벤트) | 설정 API |
| `rollup` | `events` → `agg_*` 집계 서비스와 스케줄러 |

### 4. 데이터베이스 재설계 (`V1__init.sql`)
- ClickHouse의 Materialized View / AggregatingMergeTree는 직접 이식이 불가능하여, 원천 `events` 테이블과 10개의 `agg_*` 집계 테이블로 대체
- `RollupService`가 하루 단위로 해당 날짜 집계를 삭제 후 `events`로부터 다시 계산 (멱등, 한 트랜잭션, advisory lock으로 동시 실행 방지)
- `RollupScheduler`: 5분마다 오늘 집계 갱신, 자정 직후 1시간 동안은 어제도 재계산, 기동 시 최근 7일 중 누락된 날짜 보충
- ClickHouse Dictionary(`conversion_events_dict`)는 일반 테이블 + PK 조회로 대체
- 기존에 "오늘(agg) / 과거(flat)"로 나뉘어 있던 조회 분기가 사라짐
- `ALTER TABLE … UPDATE/DELETE` 변경 쿼리를 일반 `UPDATE`/`DELETE`로 교체
- pgvector 확장(`CREATE EXTENSION vector`)과 Java 클라이언트 의존성만 준비 (현재 기능에서 벡터를 사용하지 않음)

### 5. 테스트
- `UnitTests`: JWT 왕복, 기존 Node 서버가 발급한 형태의 토큰 수락, 짧은 시크릿 거부, 주차 라벨, JSON 문자열 이스케이프 (5개)
- `ApiIntegrationTest`: Testcontainers(pgvector)로 실제 DB에서 인증, 설정, SDK, 통계, 전환 경로, 개요, 참여도, 유입, 트래픽, 사용자, 퍼널, 리포트(CSV/MD) 검증 (12개)
- `./gradlew clean build` 17개 테스트 전체 통과
- 앱을 실제로 기동하여 로그인 → 쿠키 재발급 → 인증 API, CORS preflight, `:9091/metrics`, `:9091/health`, 기동 시 백필 확인

## 트러블슈팅

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 통합 테스트 9개 실패 (`No value supplied for the SQL parameter '20'`) | 배열 슬라이스 `[1:20]`을 Spring이 `:20` 이름 파라미터로 해석 | `[1 : 20]`으로 공백 추가 |
| 테스트가 실패했을 때 이후 테스트가 빈 데이터로 계속 실행됨 | 시드 데이터 적재 실패 시 후속 처리가 없었음 | 시드 실패를 기록하고 모든 테스트가 즉시 실패하도록 수정 |
| `bootRun` 시 DB 비밀번호 인증 실패 (`28P01`) | 로컬 PC의 기존 PostgreSQL이 5432 포트를 사용 중이어서 다른 서버에 연결됨 | `docker-compose.yml`의 포트를 `${DB_PORT:-5432}`로 변경, `DB_PORT=5433`으로 실행 |
| 기동 실패 (`RollupScheduler`에 TaskExecutor 빈 2개) | `applicationTaskExecutor`와 스케줄러용 실행기 중복 | `@Qualifier("applicationTaskExecutor")` 지정, 통합 테스트에서도 스케줄러 빈을 활성화하여 재발 방지 |

## 동작 변경 사항

- **SQL 인젝션 제거**: 문자열 이어붙이기로 만들던 모든 쿼리를 바인드 파라미터로 변경
- **가짜 데이터 제거**: `acquisition/channel-groups`가 무작위 값을 반환하던 것을 실제 `events` 집계로 교체, `overview/realtime`의 시뮬레이션 트렌드 생성 제거
- **정확한 활성 사용자**: `engagement/revisit`의 DAU/WAU/MAU를 `agg_daily_users` 기반 정확 계산으로 변경 (기존에는 WAU/MAU가 비어 있었음)
- **조회 지연**: 기간 조회 KPI는 최대 5분(집계 주기) 지연될 수 있고, 실시간 지표(최근 30분, 오늘 방문자·클릭)는 `events`를 직접 조회
- **Prometheus 메트릭 이름 변경**: `http_requests_total` 등 → Micrometer 기본 이름 (`http_server_requests_seconds_*`)
- **신규 가입 승인**: `AUTH_AUTO_APPROVE` 기본값 `false` (기존 동작을 코드만으로 확인할 수 없어 보수적으로 설정)
- 유지: `overview/user-stats`의 `changes` 하드코딩 값

## 배포 전 확인 필요

1. 이벤트 수집 파이프라인(Kafka 컨슈머 등)이 이 저장소에 없어 변경하지 못함 → PostgreSQL `events` 테이블에 적재하도록 수정 필요
2. 기존 ClickHouse 데이터는 이관하지 않음 → `users`, `event_rules`, `event_button`, `conversion_events`, 원천 `events` 이관 후 `RollupService.refreshRange`로 집계 재생성 필요 (기존 bcrypt 해시는 그대로 검증됨)
3. `JWT_SECRET`, `JWT_REFRESH_SECRET`은 32바이트 이상이어야 기동됨 (같은 시크릿을 쓰면 기존 토큰도 유효)
4. Grafana 대시보드의 메트릭 이름 갱신 필요

## 참고

- 빌드 검증에 쓴 JDK 21은 세션 임시 디렉토리의 사본이므로 로컬에서는 JDK 21을 별도로 설치해야 함
- 로컬에서 5432 포트가 사용 중이면 `DB_PORT=5433 docker compose up -d` 사용
