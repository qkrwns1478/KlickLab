# LLM 분석 에이전트 Phase 6: 관측(Langfuse, Prometheus)과 Docker 구성

## 요청

`docs/plans/01-text_to_sql_LLM_분석_에이전트_구현_계획.md`의 Phase 6 구현. AWS 배포와 시크릿 관리는 실제 배포 계획이 없어 제외했다.

## 작업 내용

### 1. Langfuse 트레이싱 (`app/tracing.py`)

- Langfuse SDK 대신 공개 ingestion API(`POST /api/public/ingestion`)에 `httpx`로 직접 보낸다. 의존성이 늘지 않고 전송 내용을 테스트에서 그대로 검증할 수 있다.
- 실행 하나가 트레이스 하나이고, **트레이스 id는 `agent_runs.id`와 같다**. 종료 시 `agent_runs.trace_id`에도 저장한다.
- 난이도 분류와 매 단계 LLM 호출은 generation(입력 메시지, 응답, 토큰, 비용, 공급자·폴백 여부, 실패는 ERROR 레벨), 도구 호출은 span이다. 실행 종료 시 같은 id로 트레이스를 다시 보내 결과·태그(난이도, 상태, fallback)·요약을 채운다.
- LLM 호출 기록은 `TracedLLM`이 실행의 LLM 세션을 감싸 처리한다. 분류와 루프가 같은 세션을 쓰므로 한 곳에서 모두 잡히고, 폴백으로 모델이 바뀌어도 속성이 그대로 위임된다. 트레이싱이 꺼져 있으면 감싸지 않는다.
- 이벤트는 메모리 큐에 쌓고 백그라운드 작업이 최대 50건씩 묶어 보낸다. 5xx는 1회 재시도, 400·401·403·404는 재시도하지 않는다. 207 응답의 이벤트별 거절도 집계한다. 큐 상한(2000)을 넘으면 오래된 것부터 버린다. 전송 실패는 경고 로그만 남기고 답변에는 영향이 없다.
- 점수: 사용자 피드백(`user_feedback` 1/-1, 같은 id로 덮어씀), 평가 러너의 `execution_match`, `any_step_match`, `analysis_pass`, `fact_coverage`, `judge_grounded`, `safety_pass`. 평가는 `eval` 환경으로 보내 사용자 실행과 나눈다.
- `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`가 모두 있어야 켜진다. 없으면 `NullTracer`.
- 피드백 엔드포인트를 `async`로 바꿔 DB 저장은 `to_thread`로, 점수 전송은 이벤트 루프 안에서 한다.

### 2. 비용 계산 (`app/llm/pricing.py`)

- 모델별 단가(USD / 100만 토큰)로 호출 비용을 계산해 실행 비용을 `agent_runs.cost_usd`(그동안 항상 비어 있었음)와 `done` 요약의 `costUsd`에 남기고, Langfuse generation에는 `costDetails`로 보낸다.
- 기본 단가는 Groq gpt-oss-120b(0.15 / 0.60, 공시 가격이며 바뀔 수 있음)와 로컬 모델(0). 단가를 모르는 모델(K-EXAONE 등)은 0이 아니라 비워 둔다. `LLM_PRICES="모델=입력:출력,..."`로 덮어쓰고, 형식이 틀리면 오류를 낸다.

### 3. Prometheus (`app/metrics.py`, `GET /metrics`)

- 실행(`agent_runs_total`, `agent_run_duration_seconds`, `agent_runs_in_progress`), LLM(호출·시간·토큰·비용·오류), 폴백 실행, 도구 호출·시간, 피드백, HTTP(`http_requests_total` 등).
- 레이블은 종류가 정해진 값만 쓴다. 모델이 지어낸 도구 이름(`json` 등)은 `unknown`으로 묶고, HTTP 경로는 템플릿(`/agent/runs/{run_id}`)을 쓴다. 질문·`sdk_key`·사용자는 넣지 않는다.
- HTTP 계측은 순수 ASGI 미들웨어다. `BaseHTTPMiddleware`는 SSE 스트림과 연결 끊김 전파(실행 중단 처리)를 방해할 수 있어 쓰지 않았다. SSE의 시간은 응답 시작까지다.
- `METRICS_ENABLED=false`로 끈다. 인증이 없는 엔드포인트라 외부 공개 환경에서는 프록시에서 막아야 한다(README에 적음).
- 의존성 `prometheus-client` 추가(`uv.lock` 갱신).

### 4. Docker 구성

- `agent/Dockerfile`: uv 다단계 빌드, 비루트 사용자, 헬스체크. 로컬 임베딩(torch)은 이미지가 수 GB로 커져 빌드 인자 `WITH_EMBEDDING=true`일 때만 넣는다(기본 `EMBEDDING_PROVIDER=none`).
- `backend/Dockerfile`: Gradle 빌드 후 JRE 알파인 이미지에서 실행, 헬스체크는 Actuator `/health`. Windows 체크아웃의 CRLF `gradlew`가 실행되지 않아 `sed`로 정규화한다.
- `frontend/Dockerfile` + `nginx.conf`: Vite 정적 빌드를 nginx로 서빙하고 `/api`는 backend, `/agent`는 agent로 전달한다. SSE를 위해 `/agent/`는 버퍼링을 끄고 읽기 제한 시간을 늘렸다.
- 루트 `docker-compose.yml`: postgres, backend, agent, frontend, Langfuse v3(web, worker, 전용 postgres, clickhouse, minio, redis). Langfuse 프로젝트·API 키·관리자 계정은 `LANGFUSE_INIT_*`로 처음부터 만든다. 에이전트 DB 롤의 로그인은 일회성 서비스 `agent-db-roles`가 백엔드 마이그레이션(V4) 뒤에 열어 준다(README의 수동 `ALTER ROLE`을 대체). 호스트 포트는 모두 환경변수로 바꿀 수 있다. 비밀번호·키 기본값은 개발용이다.
- 에이전트는 Langfuse가 준비되길 기다리지 않는다(`service_started`). 트레이싱은 선택 기능이기 때문이다.
- 루트 `.env.example`, `agent/.env.example`, README 7·8절 추가. 기존 `backend/docker-compose.yml`(DB만, 로컬 개발용)은 그대로 둔다.

### 5. Prometheus + Grafana (후속, 선택)

- 계획에 없던 항목이다. 사용자 요청으로 추가했고, 로깅 스택(Loki 등)은 과하다고 판단해 넣지 않았다.
- compose 프로파일 `monitoring`(`docker compose --profile monitoring up -d`)으로만 뜬다. 기본 `up`에는 포함되지 않는다.
- `monitoring/prometheus.yml`: agent(`agent:8000/metrics`)와 backend(`backend:9091/metrics`)를 15초마다 수집, 보관 15일.
- `monitoring/grafana/`: 데이터소스와 대시보드 프로비저닝, 대시보드 `klicklab-agent`(패널 17개: 실행, LLM, 도구·피드백, HTTP). 백엔드는 히스토그램 버킷이 없어 p95 대신 평균 응답 시간을 쓴다.
- 포트는 `PROMETHEUS_PORT`(9090), `GRAFANA_PORT`(3001)로 바꾼다. 둘 다 127.0.0.1에만 바인딩한다.

## 검증

- `pytest` 318건 통과(신규 27건: 단가, 트레이서 전송·재시도·거절·큐 초과, 루프 트레이스 구성, 실패 generation, Langfuse 장애 시 실행 무영향, 메트릭 증가, 도구 이름 레이블 제한, `/metrics`, 피드백 점수), `ruff check`·`ruff format --check` 통과.
- 포트를 바꾼(14000 등) 별도 프로젝트로 `docker compose up -d --build` 실제 기동: 이미지 3개 빌드, 모든 서비스 healthy, `agent-db-roles` 정상 종료, 에이전트가 부여된 롤로 DB 접속(`GET /agent/runs` 200), nginx 경유 `/agent/health` 200, `/metrics` 응답 확인.
- 모니터링 프로파일 실제 기동: Prometheus 타깃 2개(agent, backend) up, Grafana에 데이터소스와 대시보드 프로비저닝 확인, 대시보드 쿼리가 쓰는 메트릭 이름(`http_requests_total`, `agent_runs_in_progress`, `http_server_requests_seconds_*`)이 실제로 수집되는 것을 확인했다. 단, 에이전트 실행 메트릭(LLM·도구 패널)은 LLM 키가 없어 값이 채워진 화면은 보지 못했고, 패널 렌더링을 브라우저로 보지는 않았다.
- 실제 Langfuse(v3)에 에이전트 `Tracer`로 트레이스·generation·span·점수를 보내고 공개 API로 다시 읽어 환경·사용자·세션·태그·토큰·비용(0.00027)·점수가 반영된 것을 확인했다. 확인 후 검증용 스택은 볼륨까지 삭제했다.

## 미확인·한계

- LLM 키 없이 확인해서, 실제 질문 실행이 Langfuse에 남는 전체 경로는 실행하지 못했다. 같은 코드 경로를 단위 테스트(가짜 LLM + 가짜 Langfuse)와, 실제 Langfuse 수신 프로브(수동 호출)로 나눠 검증했다.
- 브라우저에서 컨테이너 대시보드를 눌러 보는 확인은 하지 않았다(HTTP 응답까지만).
- 단일 턴 Text-to-SQL(`/agent/ask`)은 트레이싱·메트릭 대상에서 제외했다(Tool Loop만 대상).
- Langfuse dataset run은 쓰지 않았고, 평가 결과는 트레이스 점수와 기존 `evals/reports/*.md`로 남긴다.
- AWS 배포, 시크릿 관리는 요청대로 제외.
