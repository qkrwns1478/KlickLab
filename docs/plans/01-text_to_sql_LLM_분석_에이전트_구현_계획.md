# Text-to-SQL 기반 LLM 분석 에이전트 구현 계획

- 작성일: 2026-11-10

## 1. 목표

KlickLab의 클릭스트림 데이터 위에 **자연어로 질문하면 스스로 SQL을 만들어 조회·검증하고, 근거 데이터와 함께 분석 결과를 돌려주는 단일 에이전트**를 추가한다.

> "지난주 대비 이번 주 참여도가 떨어진 페이지를 찾고, 원인을 분석해 줘."
> → 질문 분류 → 스키마·지표 정의 검색 → SQL 생성·검증·실행(반복) → 가설과 근거 데이터 → 리포트

입증할 역량(제안 문서 우선순위 표 기준)

| 우선순위 | 기능 | 역량 | 단계 |
| --- | --- | --- | --- |
| 1 | 자연어 → SQL 생성·검증·실행 | Text-to-SQL, Python | Phase 1 |
| 2 | 필요한 데이터를 반복 조회하는 에이전트 | Tool Calling, Tool Loop | Phase 2 |
| 3 | 지표 정의·테이블 스키마 검색 | RAG | Phase 3 |
| 4 | FastAPI 에이전트 서버 | Python Backend | Phase 1~2 |
| 5 | SQL 정확도·답변 품질 평가 | LLM Evaluation | Phase 4 |
| 6 | Docker·AWS 배포, 실행 추적 | AI Platform, Observability | Phase 5~6 |

범위 밖: 멀티 에이전트, 데이터 쓰기/수정, 범용 챗봇 기능, 새 백오피스 프레임워크 도입.

## 2. 현재 상태와 제안 문서와의 차이

제안 문서는 ClickHouse 기준으로 쓰였지만 현재 저장소는 **PostgreSQL 17 + pgvector 단독** 구조로 마이그레이션되었다. 계획은 현재 구조를 기준으로 한다.

| 항목 | 현재 상태 | 에이전트에서의 활용 |
| --- | --- | --- |
| 원천 데이터 | `events` (sdk_key 단위 멀티 테넌트) | 세부 드릴다운용, 비용이 큰 조회 |
| 집계 데이터 | `agg_*` (RollupService), `minutes/hourly/daily/weekly_*` (Spring Batch) | 기본 조회 대상 (빠르고 저렴) |
| 벡터 검색 | `CREATE EXTENSION vector` 이미 적용 | 스키마·지표 정의 RAG 저장소 |
| 인증 | Spring JWT(HS256), 클레임 `userId`, `email`, `sdk_key` | FastAPI가 같은 시크릿으로 검증 → 테넌트 격리 |
| 데모 데이터 | `backend/seed/clickstream_seed.sql` (패턴이 심어진 5주치 데이터) | 평가용 정답 데이터셋의 근거 |
| 마이그레이션 | Flyway (`backend/src/main/resources/db/migration`) | 에이전트 테이블도 Flyway로 관리 (스키마 소유자 단일화) |

시드에 심어 둔 패턴은 "원인 분석" 질문의 정답으로 그대로 쓸 수 있다.

- 최근 2~8일 전 `nov_mega_sale` 캠페인(naver cpc / instagram / kakao) 신규 유입 급증
- 15일 전 모바일 결제 장애 → 모바일 `/checkout → /checkout/success` 전환 0
- 화요일 뉴스레터로 email 유입 급증, 주말 방문 증가
- 점심·저녁 피크 / instagram·youtube 이탈률 높음, email·naver cpc 전환 의도 높음

## 3. 아키텍처

```
┌──────────── frontend (React) ────────────┐
│ /dashboard/agent  채팅 · 실행 단계 · SQL · 결과 차트 │
└───────────────┬──────────────────────────┘
                │ JWT (기존 로그인 토큰 그대로)
                ▼  SSE
┌──────────── agent (Python / FastAPI) ────────────┐
│ Router(난이도 분류) → Budget 결정                    │
│ Agent Loop ── tools ─┬ search_knowledge (pgvector)  │
│                      ├ describe_table               │
│                      ├ run_sql (검증 → 실행)          │
│                      └ final_answer (리포트 + 차트)   │
│ Tracing: Langfuse  /  실행 로그: agent_runs, agent_steps │
└───────────────┬──────────────────────────┘
                │ read-only role + RLS(sdk_key)
                ▼
        PostgreSQL 17 + pgvector  ◀── backend (Spring) 수집·집계
```

설계 원칙

- **Spring 백엔드는 건드리지 않는다.** 에이전트는 독립 Python 서비스로 두고 DB만 공유한다. (포트폴리오에서 Python 서비스 경계가 명확히 드러남)
- **LLM이 만든 SQL은 신뢰하지 않는다.** 정적 검증 + DB 권한 + 실행 제한의 3중 방어를 해야 한다.
- **비용은 질문 난이도에 따라 미리 정한다.** 루프가 예산을 넘으면 그 시점까지의 근거로 답한다.

## 4. 기술 스택

| 영역 | 선택 | 비고 |
| --- | --- | --- |
| 언어/런타임 | Python 3.12, uv | 의존성·가상환경 관리 |
| 서버 | FastAPI, Uvicorn, Pydantic v2 | SSE 스트리밍(`sse-starlette`) |
| DB 접근 | psycopg 3 (async) + 커넥션 풀 | ORM 없이 SQL 직접 사용 |
| LLM | Anthropic Claude API (tool use) | 메인 루프 `claude-sonnet-5-5`, 분류·요약 `claude-haiku-5-5`. `LLMClient` 인터페이스로 감싸 교체 가능하게 |
| SQL 검증 | sqlglot (postgres dialect) | AST 기반 화이트리스트 검사 |
| 임베딩 | 로컬 다국어 임베딩 모델(예: bge-m3) 또는 외부 임베딩 API | 한국어 질문 대응, `EmbeddingClient`로 추상화 |
| 관측 | Langfuse (self-host, docker) | 트레이스·토큰·비용·평가 점수 |
| 테스트/평가 | pytest, 자체 eval 러너 | CI에서 회귀 평가 |

## 5. 디렉토리 구조

```
agent/
├── pyproject.toml
├── Dockerfile
├── .env.example                 # DB_URL(read-only), JWT_SECRET, ANTHROPIC_API_KEY, LANGFUSE_*
├── app/
│   ├── main.py                  # FastAPI 앱, 라우터 등록, CORS
│   ├── config.py                # pydantic-settings
│   ├── auth.py                  # JWT 검증 → AuthUser(user_id, sdk_key)
│   ├── api/
│   │   └── runs.py              # POST /agent/runs (SSE), GET /agent/runs, GET /agent/runs/{id}
│   ├── agent/
│   │   ├── router.py            # 질문 난이도 분류 → Budget
│   │   ├── budget.py            # 툴 호출·토큰·시간 예산과 소진 처리
│   │   ├── loop.py              # tool loop 본체
│   │   ├── prompts.py           # 시스템 프롬프트, 답변 형식
│   │   └── tools/
│   │       ├── search_knowledge.py
│   │       ├── describe_table.py
│   │       ├── run_sql.py
│   │       └── final_answer.py
│   ├── sql/
│   │   ├── guard.py             # sqlglot 검증·재작성 (LIMIT 주입 등)
│   │   └── executor.py          # 트랜잭션, SET LOCAL, timeout, 결과 직렬화
│   ├── knowledge/
│   │   ├── catalog/             # 시맨틱 레이어 YAML (테이블, 지표, 예시 쿼리)
│   │   ├── indexer.py           # YAML → 임베딩 → agent_knowledge 적재
│   │   └── retriever.py         # 하이브리드 검색 (벡터 + 키워드)
│   ├── llm/                     # LLMClient, EmbeddingClient 구현
│   └── tracing.py               # Langfuse 연동
├── evals/
│   ├── datasets/                # golden_sql.yaml, analysis_questions.yaml
│   ├── run_eval.py              # 평가 실행 → 리포트(JSON/Markdown)
│   └── judges.py                # 결과 비교, LLM-as-judge
└── tests/
```

DB 마이그레이션은 Flyway에 추가한다: `backend/src/main/resources/db/migration/V4__agent.sql`

## 6. 세부 설계

### 6.1 질문 분류와 실행 예산

`router.py`가 가벼운 모델로 질문을 분류하고 예산을 정한다. 분류 결과와 예산은 실행 로그에 남긴다.

| 난이도 | 예시 | 최대 툴 호출 | 최대 SQL 실행 | 모델 | 타임아웃 |
| --- | --- | --- | --- | --- | --- |
| `lookup` | "어제 방문자 수는?" | 3 | 1 | haiku | 15s |
| `compare` | "지난주 대비 이번 주 채널별 전환율 변화" | 6 | 3 | sonnet | 40s |
| `diagnose` | "참여도가 떨어진 페이지와 원인을 분석해 줘" | 15 | 8 | sonnet | 120s |
| `out_of_scope` | 데이터와 무관한 질문, 쓰기 요청 | 0 | 0 | – | 즉시 거절 |

- 예산 항목: 툴 호출 수, SQL 실행 수, 누적 입력/출력 토큰, 경과 시간.
- 예산의 80%에 도달하면 시스템 메시지로 "남은 예산 안에서 결론을 내라"고 알리고, 소진 시 `final_answer`만 허용한다.
- 분류가 틀렸을 때를 위해 루프 중 1회에 한해 상위 난이도로 승격을 요청할 수 있다(`request_more_budget`). 승격 여부는 평가에서 비용 대비 정확도로 검증한다.

### 6.2 Tool Loop

```
messages = [system, user_question]
while budget.ok():
    resp = llm.create(messages, tools=allowed_tools(budget))
    if resp.stop_reason != "tool_use": break
    for call in resp.tool_calls:
        result = dispatch(call)            # 실패도 결과로 돌려줌 (에러 메시지 + 힌트)
        trace.step(call, result, usage)    # agent_steps 적재 + SSE 이벤트 발행
    messages += [resp, tool_results]
return final_answer or forced_summary()
```

| 툴 | 입력 | 출력 | 비고 |
| --- | --- | --- | --- |
| `search_knowledge` | query, kind(table/metric/example) | 상위 k개 문서 | 지표 정의·예시 SQL 포함 |
| `describe_table` | table_name | 컬럼, 타입, 설명, 샘플 3행 | 화이트리스트 테이블만 |
| `run_sql` | sql, purpose | 컬럼, 행(최대 200), 행 수, 실행 시간 | 검증 실패 시 사유 반환 → 자가 수정 |
| `final_answer` | summary, findings[], evidence[], chart | 종료 | evidence는 실행된 SQL step id를 참조 |

- `final_answer`의 각 주장(finding)은 반드시 실제 실행한 SQL 결과(step id)를 근거로 연결해야 한다. 근거 없는 주장은 서버에서 거부하고 재요청한다(환각 억제).
- 같은 SQL 반복 실행은 캐시 결과를 반환하고 예산을 차감하지 않는다.

### 6.3 SQL 안전장치

1. **정적 검증 (`sql/guard.py`, sqlglot)**
   - 단일 문장, `SELECT`/`WITH ... SELECT`만 허용
   - 허용 테이블 화이트리스트(`events`, `agg_*`, `*_metrics`, `*_click_summary`, `*_top_elements`, `*_user_distribution`, `*_page_stats`, `conversion_events`). `users`, `event_rules` 등 계정 테이블 차단
   - 위험 함수 차단(`pg_sleep`, `pg_read_file`, `dblink`, `set_config` 등)
   - `LIMIT` 없으면 주입, 상한 1,000행
   - `events` 조회 시 기간 조건이 없으면 거부 (원천 테이블 풀스캔 방지)
2. **DB 권한**
   - 전용 롤 `klicklab_agent_ro`: 화이트리스트 테이블 `SELECT`만 부여 (실행 로그·지식 베이스 쓰기는 별도 롤 `klicklab_agent`가 담당)
   - RLS 정책: `sdk_key = current_setting('app.sdk_key')` — 실행기는 트랜잭션마다 `SET LOCAL app.sdk_key = <JWT의 sdk_key>` 설정. LLM이 `sdk_key` 조건을 빼먹거나 다른 값을 넣어도 다른 테넌트 데이터는 보이지 않는다.
     - (Phase 4 변경) `app.sdk_key`는 쿼리 안의 `set_config`로 바꿀 수 있어, V5에서 읽기 전용 롤이 모르는 테넌트 토큰(`app.tenant_token`) 기준으로 바꿨다.
3. **실행 제한**
   - `SET LOCAL statement_timeout = '5s'`, `default_transaction_read_only = on`
   - 실행 전 `EXPLAIN (FORMAT JSON)`으로 예상 비용 확인, 임계값 초과 시 집계 테이블 사용을 권하는 메시지로 반려

### 6.4 지식 베이스 (RAG)

정확한 SQL 생성에는 스키마 자체보다 **"이 서비스에서 지표를 어떻게 계산하는가"**가 중요하다. 시맨틱 레이어를 YAML로 직접 작성하고 이를 검색한다.

`knowledge/catalog/` 예시

```yaml
# metrics/bounce_rate.yaml
kind: metric
name: 이탈률 (bounce rate)
aliases: [바운스율, 반송률]
definition: 단일 페이지만 보고 떠난 세션 비율
sql: SUM(bounced_sessions)::float / NULLIF(SUM(sessions), 0)
source_table: agg_traffic_hourly
grain: [summary_date, summary_hour, traffic_source, traffic_medium, landing_page]
notes: 세션 속성은 세션 첫 이벤트 기준
```

| 문서 종류 | 내용 | 출처 |
| --- | --- | --- |
| table | 테이블·컬럼 설명, grain, 갱신 주기, 어떤 질문에 쓰는지 | `V1__init.sql`, `V3__aggregation_tables.sql` 주석 + 수동 보강 |
| metric | 참여도, 체류 시간, 이탈률, 전환율, DAU/WAU/MAU, 신규/재방문 등 | 기존 Controller의 집계 SQL을 정리 |
| example | 질문–SQL 쌍 (few-shot) | 기존 대시보드 API 쿼리 + 평가셋 일부 |
| glossary | 채널 그룹, segment_type 값, 이벤트명 의미 | 시드·SDK 문서 |

- 저장: `agent_knowledge(id, kind, name, content, metadata jsonb, embedding vector(N))` + HNSW 인덱스
- 검색: 벡터 유사도 + `pg_trgm`/키워드 점수 하이브리드, kind별 상위 k
- 테이블 수가 적으므로 Phase 1에서는 핵심 스키마 요약을 시스템 프롬프트에 직접 넣고, Phase 3에서 RAG로 대체한 뒤 **정확도·토큰 차이를 평가로 비교**한다(포트폴리오 서술 포인트).

### 6.5 API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/agent/runs` | `{question}` → SSE 스트림 (`classified`, `tool_call`, `tool_result`, `answer`, `error`, `done`) |
| `GET` | `/agent/runs` | 내 실행 목록 (질문, 난이도, 상태, 비용, 시각) |
| `GET` | `/agent/runs/{id}` | 실행 상세 (단계별 툴 호출, SQL, 결과, 토큰) |
| `POST` | `/agent/runs/{id}/feedback` | 👍/👎 + 코멘트 (평가셋 후보 수집) |
| `GET` | `/agent/health` | 헬스체크 |

인증: `Authorization: Bearer <access token>`을 Spring과 같은 `JWT_SECRET`으로 검증하고 `sdk_key` 클레임을 사용한다.

### 6.6 실행 로그 테이블 (`V4__agent.sql`)

```sql
CREATE TABLE agent_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sdk_key       VARCHAR(64) NOT NULL,
    user_id       UUID        NOT NULL,
    question      TEXT        NOT NULL,
    difficulty    VARCHAR(20),
    status        VARCHAR(20) NOT NULL,   -- running / succeeded / budget_exhausted / failed / rejected
    answer        JSONB,
    tool_calls    INTEGER     NOT NULL DEFAULT 0,
    input_tokens  INTEGER     NOT NULL DEFAULT 0,
    output_tokens INTEGER     NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(10, 6),
    latency_ms    INTEGER,
    trace_id      VARCHAR(64),            -- Langfuse
    feedback      SMALLINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_steps (
    run_id     UUID     NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    seq        SMALLINT NOT NULL,
    tool       VARCHAR(50) NOT NULL,
    input      JSONB    NOT NULL,
    output     JSONB,
    error      TEXT,
    duration_ms INTEGER,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE agent_knowledge ( ... );       -- 6.4 참고
-- + klicklab_agent / klicklab_agent_ro 롤, GRANT, RLS 정책
```

### 6.7 프론트엔드 (`/dashboard/agent`)

- 사이드바에 탭 하나 추가, 기존 `Dashboard.tsx` 라우팅에 연결
- 좌측: 실행 기록 목록 / 중앙: 질문 입력과 답변 / 답변 아래 접을 수 있는 실행 단계(툴 호출 → SQL → 결과 표)
- 답변의 각 finding 옆에 근거 step으로 이동하는 링크, `chart` 스펙은 기존 Recharts 컴포넌트(`HorizontalBarChart`, `HorizontalLineChart`)로 렌더링
- UI 규칙에 따라 보조 설명 문구 없이 레이아웃(단계 순서, 접힘 구조)으로 흐름을 전달
- 개발 환경은 Vite proxy로 `/agent` → FastAPI(예: 8000)

### 6.8 평가

| 평가셋 | 규모 | 채점 방식 |
| --- | --- | --- |
| `golden_sql.yaml` (lookup/compare) | 40~60문항 | 정답 SQL과 **실행 결과 비교**(행 집합 동일성, 수치 허용 오차). SQL 문자열 비교는 하지 않음 |
| `analysis_questions.yaml` (diagnose) | 10~15문항 | 시드에 심은 패턴을 정답 키워드/사실로 정의 → 규칙 채점 + LLM-as-judge(근거 인용 여부, 사실 정확성) |
| 안전성 | 15문항 | 쓰기 시도, 타 테넌트 조회, 계정 테이블 조회, 프롬프트 인젝션 → 전부 차단되어야 통과 |

측정 지표: 실행 정확도, 원인 적중률, SQL 1회 성공률/자가 수정 횟수, 평균 툴 호출 수, 토큰·비용·지연(난이도별), 예산 소진 비율.

- 평가 결과는 Langfuse dataset run과 `evals/reports/*.md`로 남겨 프롬프트·RAG·예산 변경 전후를 비교한다.
- 시드는 실행 날짜 기준 상대 날짜로 생성되므로 정답 SQL도 상대 날짜(`current_date - N`) 기준으로 작성한다.

## 7. 구현 단계

### Phase 0. 준비

- [x] `agent/` 프로젝트 골격 (uv, FastAPI, ruff, pytest)
- [x] `V4__agent.sql`: 실행 로그 테이블, `klicklab_agent` 롤, RLS 정책
- [x] 시드 적재 + 집계 백필 후 데모 계정으로 로컬 환경 확인

- 작업 로그: [Phase 0 골격 및 V4 마이그레이션](../logs/2026-11-11/01-에이전트_Phase0_골격_및_V4_마이그레이션.md)

### Phase 1. 단일 턴 Text-to-SQL

- [x] JWT 검증 의존성, `sdk_key` 주입
- [x] `sql/guard.py`, `sql/executor.py` + 단위 테스트(차단 케이스 위주)
- [x] 스키마 요약을 프롬프트에 넣고 질문 → SQL 1회 생성 → 실행 → 자연어 답변
- [x] `golden_sql.yaml` 초안 20문항, 기준 정확도 측정

- 작업 로그: [Phase 1 단일 턴 Text-to-SQL (K-EXAONE 2.5)](../logs/2026-11-11/02-에이전트_Phase1_단일턴_Text-to-SQL.md)

### Phase 2. Tool Loop와 실행 예산

- [x] Claude tool use 기반 루프, 4개 툴, 실패 결과 피드백을 통한 자가 수정
- [x] 난이도 분류기와 예산 관리, 강제 종료 시 요약
- [x] `final_answer` 근거 연결 검증
- [x] SSE 스트리밍, `agent_runs`/`agent_steps` 적재

- 작업 로그: [Phase 2 Tool Loop와 실행 예산 (Groq gpt-oss-120b)](../logs/2026-11-11/03-에이전트_Phase2_Tool_Loop와_실행_예산.md)

### Phase 3. 지식 베이스 (RAG)

- [x] 시맨틱 레이어 YAML 작성 (테이블, 지표, 예시, 용어)
- [x] 인덱서·하이브리드 검색, `search_knowledge` 툴 연결
- [x] 프롬프트 직접 주입 방식 vs RAG 방식 정확도·토큰 비교 (단일 턴 기준. Tool Loop 비교는 Phase 4)

- 작업 로그: [Phase 3 지식 베이스 RAG (K-EXAONE 2.5)](../logs/2026-11-11/04-에이전트_Phase3_지식_베이스_RAG.md)

### Phase 4. 평가 자동화

- [x] 평가셋 확장 (golden 44, diagnose 12, 안전성 21)
- [x] `run_eval.py`, LLM-as-judge, 리포트 생성 (Tool Loop·judge 실측은 LLM 한도로 미실행)
- [x] GitHub Actions에서 PR마다 축소 평가셋 회귀 실행 (워크플로 작성, GitHub 실행은 미확인)
- 안전성 평가에서 찾은 RLS 우회(guard 우회 시 `set_config`로 테넌트 전환)를 V5 테넌트 토큰으로 수정

- 작업 로그: [Phase 4 평가 자동화 (Groq 미사용, K-EXAONE 2.5 일부 실측)](../logs/2026-11-11/05-에이전트_Phase4_평가_자동화.md)

### Phase 5. 백오피스 UI

- [ ] `/dashboard/agent` 탭, 채팅·실행 단계·SQL·결과 표·차트
- [ ] 실행 기록 목록·상세, 피드백 버튼

### Phase 6. 관측과 배포

- [ ] Langfuse 연동 (트레이스, 토큰·비용, 평가 점수)
- [ ] `agent/Dockerfile`, `docker-compose.yml`에 agent·langfuse 서비스 추가
- [ ] AWS 배포 (ECS 또는 EC2 + RDS), 시크릿 관리, Prometheus 메트릭(`/metrics`) 노출

## 8. 리스크와 대응

| 리스크 | 대응 |
| --- | --- |
| 잘못된 SQL이 그럴듯한 숫자를 반환 | 실행 결과 기반 평가, 지표 정의 RAG, 근거 step 강제 |
| 테넌트 데이터 유출 | sqlglot 검증과 별개로 RLS로 DB 레벨 격리, 안전성 평가셋 |
| 원천 `events` 풀스캔으로 DB 부하 | 기간 조건 강제, EXPLAIN 비용 상한, statement_timeout, 집계 테이블 우선 안내 |
| 루프 폭주로 비용 증가 | 난이도별 예산, 동일 SQL 캐시, 예산 소진 시 강제 요약 |
| 프롬프트 인젝션(질문·데이터 값에 지시문) | 툴 결과는 데이터로만 취급하도록 프롬프트 분리, 읽기 전용 권한으로 피해 범위 제한 |
| 시드 날짜가 실행일 기준이라 평가 결과 변동 | 정답을 상대 날짜로 정의, 평가 전 시드 재생성 |

## 9. 완료 기준

- 데모 계정으로 "지난주 대비 이번 주 참여도가 떨어진 페이지와 원인"을 질문하면, 시드에 심은 원인(캠페인 유입 변화, 모바일 결제 장애 등) 중 해당하는 것을 근거 SQL과 함께 제시한다.
- golden SQL 실행 정확도, 원인 적중률, 난이도별 평균 비용·지연이 리포트로 남아 있고, 안전성 평가셋을 100% 통과한다.
- docker compose 한 번으로 backend·agent·frontend·postgres·langfuse가 함께 뜬다.
