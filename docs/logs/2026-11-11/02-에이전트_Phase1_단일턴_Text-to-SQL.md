# LLM 분석 에이전트 Phase 1: 단일 턴 Text-to-SQL

## 요청

`docs/plans/01-text_to_sql_LLM_분석_에이전트_구현_계획.md`의 Phase 1 구현.
계획 문서는 Claude API 기준이지만, 이번에는 **K-EXAONE 2.5 API(`EXAONE_API_KEY`)** 로 구현하고 성능을 측정한 뒤 다른 모델로의 교체를 검토한다.

## 작업 내용

### 1. LLM 클라이언트 (`app/llm/`)

- `LLMClient` 프로토콜(`chat(messages, max_tokens, **params) -> ChatResult`)로 공급자를 감쌌다. 교체 시 구현체와 `build_llm_client` 분기만 추가하면 된다.
- `OpenAICompatClient`(httpx): K-EXAONE 2.5는 OpenAI Chat Completions 호환이다.
  - 엔드포인트 `https://api.exaone.ai/v1/chat/completions`, 모델 `k-exaone_v2.5`, Bearer 인증
  - 추론을 끌 수 없고 `reasoning_effort`(low/high/max)로만 조절한다. 추론 토큰이 `max_tokens`에 포함되므로 SQL 생성은 16384로 넉넉하게 둔다.
  - `reasoning_content`, `usage.reasoning_tokens`를 함께 수집한다.
- 무료 등급 한도가 **초당 1회 / 하루 100회**라서 요청 간 최소 간격(1초)을 지키고, 429·5xx는 `retry-after(-ms)` 헤더만큼 기다렸다 재시도한다.

### 2. SQL 안전장치 (`app/sql/`)

- `guard.py`(sqlglot, postgres)
  - 단일 문장, `SELECT`/`WITH … SELECT`/집합 연산만 허용. 데이터 변경 CTE(`WITH d AS (DELETE …)`), `SELECT INTO`, `FOR UPDATE`, `SET`/`COPY`/트랜잭션 문 차단
  - 테이블 화이트리스트(V4의 RLS 대상 33개와 동일), `public` 외 스키마 차단, CTE 이름은 허용
  - 함수 차단: `pg_*`, `lo_*`, `dblink*`, `txid_*`, `set_config`, `current_setting`, `query_to_xml` 계열 등
  - `events` 조회 시 해당 SELECT의 WHERE 절에 `timestamp` 비교 조건 필수
  - LIMIT 없음/`LIMIT ALL`/상한(1,000) 초과 → 원문을 `SELECT * FROM (…) LIMIT 1000`으로 감싼다. 비상수 LIMIT은 거부
  - 검증 후 SQL을 sqlglot으로 **다시 생성하지 않고 원문 그대로 실행**한다(재생성 과정의 의미 변화 방지).
- `executor.py`
  - 트랜잭션마다 `SET TRANSACTION READ ONLY`, `set_config('app.sdk_key' / 'statement_timeout' / 'TimeZone', …, true)` 후 실행하고 항상 롤백
  - `EXPLAIN (FORMAT JSON)` 예상 비용이 상한(기본 200,000)을 넘으면 집계 테이블 사용을 권하는 메시지로 반려. 로컬 데모 데이터 기준 30일치 `events` 집계가 약 3만이다.
  - 오류를 `timeout` / `permission` / `too_expensive` / `error`로 분류, 결과 값을 JSON 직렬화 가능한 형태로 변환(Decimal, 날짜, NaN 등)
  - 계획은 psycopg async였으나 **동기 풀 + `asyncio.to_thread`** 로 바꿨다. psycopg async는 Windows 기본 이벤트 루프(Proactor)에서 동작하지 않는다.

### 3. 단일 턴 파이프라인 (`app/agent/`)

- `prompts.py`: 핵심 스키마 요약(agg_*, events, 값 도메인), 지표 정의(이탈률·참여율·전환율·체류 시간 등, 백엔드 RollupService/Controller 계산식 기준), 기간 표현(최근 N일, 이번 주/지난주, 이번 달)을 시스템 프롬프트에 직접 넣었다. Phase 3에서 RAG로 옮겨 비교할 기준선이다.
  - `daily_metrics.visitors`(1,522)와 `agg_daily_users`(1,346)는 같은 날짜에도 값이 달라, 방문자 수는 `agg_*` 기준으로 쓰도록 명시했다. `minutes/hourly/daily/weekly_*`는 배치 지연이 있어 해당 지표가 명시된 경우에만 쓰게 했다.
  - 답변 프롬프트는 결과 안의 문자열을 지시문으로 따르지 않도록 분리했다.
- `text_to_sql.py`: 질문 → SQL 1회 생성(```sql 블록 추출) → guard → 실행 → 답변(결과 최대 50행 전달). 상태는 `succeeded` / `rejected` / `failed` / `out_of_scope`(모델이 `NO_SQL:`로 응답). 자가 수정은 Phase 2 범위라 넣지 않았다.

### 4. API (`app/api/ask.py`)

- `POST /agent/ask` `{question}`(1~500자) → `status, sql, answer, error, result{columns, rows, rowCount, truncated}, usage, timings` (camelCase, 비스트리밍)
- JWT의 `sdk_key`를 실행기에 넘긴다. 파이프라인(LLM 클라이언트·커넥션 풀)은 첫 요청 때 생성하고 앱 종료 시 닫는다. LLM 오류는 502, 키 미설정은 503.

### 5. 평가 (`evals/`)

- `datasets/golden_sql.yaml`: 20문항(lookup 14, compare 6). 정답 SQL은 `current_date` 기준 상대 날짜이며 실행 전 모두 실제 DB에서 결과가 나오는지 확인했다. 순위·추이 문항은 `order_matters`.
- `matching.py`: 실행 결과 비교. 정답 컬럼마다 값이 같은 예측 컬럼을 대응시켜(컬럼명·순서·추가 컬럼 무시) 행 집합을 비교한다. 수치 허용 오차(상대 0.5% / 절대 0.01), NULL=0, 자정 타임스탬프=날짜.
- `run_eval.py`: 문항당 SQL 생성 1회만 호출(답변 단계 제외)하고 `evals/reports/`에 Markdown·JSON 리포트를 남긴다.

### 6. 설정

- `config.py`: `LLM_PROVIDER`, `EXAONE_*`, `LLM_SQL_/ANSWER_REASONING_EFFORT`, 토큰·타임아웃·레이트 리밋, SQL 실행 제한 항목 추가
- 의존성: `httpx`(dev → 런타임), `sqlglot`, `pyyaml`
- `DB_PORT` 기본값 5432 → **5433**: 로컬 `klicklab-postgres` 컨테이너가 5433에 매핑돼 있고(백엔드 `.env`도 5433), 호스트 5432는 별개의 PostgreSQL이 사용 중이다.

## 성능 측정 (K-EXAONE 2.5, golden 20문항)

| reasoning_effort | 실행 정확도 | lookup | compare | 생성 지연 평균 / 중앙값 / 최대 | 평균 출력 토큰(추론) |
| --- | --- | --- | --- | --- | --- |
| high | **100% (20/20)** | 100% | 100% | 20.2s / 13.5s / 73.9s | 944 (827) |
| low | 95% (19/20) | 100% | 83.3% | 18.3s / 11.2s / 51.5s | 733 (626) |

- 리포트: `agent/evals/reports/20261111-0942-golden_sql-k-exaone_v2_5-high.md`, `…-0950-…-low.md`
- low의 실패(compare-05)는 값은 맞지만 두 기간을 열이 아닌 행으로 반환해 모양이 달랐다. 비교기가 전치된 결과를 같다고 보지 않는다.
- 생성 속도가 약 45 tok/s라 지연은 대부분 추론 토큰 수에 비례한다. low는 추론 토큰을 약 24% 줄이지만 지연 감소는 약 10%에 그쳐 기본값은 high로 둔다.
- 입력 토큰은 질문당 약 1,700(스키마 요약 포함).
- HTTP 종단 확인: "최근 7일 결제 완료 건수가 가장 많았던 날"은 SQL 생성 10.5초 + 답변 4.7초로 정답을 냈고, "users 테이블 이메일 삭제" 요청은 SQL 없이 `out_of_scope`로 거절했다.

### 해석과 다음 검토 사항

- 프롬프트에 지표 정의와 기간 표현을 명시했기 때문에 현재 20문항은 대부분 정의를 그대로 옮기면 풀린다. 변별력을 위해 Phase 4에서 모호한 표현, 다단계 계산, events 드릴다운 문항을 늘려야 한다.
- 정확도는 충분하지만 **지연(compare 문항 45~74초)과 일일 100회 한도**가 Phase 2 Tool Loop(질문당 호출 수 회~15회)에 가장 큰 제약이다. 다른 모델과 비교할 때 같은 평가셋으로 정확도·지연·토큰을 함께 비교한다.

## 검증

- `ruff check`, `ruff format --check` 통과
- `pytest` 88건 통과: guard 차단·허용 케이스, LLM 클라이언트(요청 형식, 429 재시도, 4xx 즉시 실패), 파이프라인(가짜 LLM/실행기), API, 결과 비교기, 실행기 통합 테스트(로컬 DB가 있을 때만 실행: RLS 격리, 쿼리 내 `sdk_key` 조건 무시, guard 우회 쓰기 차단, `users` 권한 거부, 타임아웃, 타임존)

## 참고

- 로컬 DB에서 `klicklab_agent_ro` / `klicklab_agent` 롤의 로그인을 `.env.example` 안내대로 열었다.
- `agent/.env`의 `JWT_SECRET`이 비어 있어 서버의 인증 API는 모두 401이다. HTTP 종단 확인은 임시 시크릿을 환경변수로 주입해 진행했다. 백엔드와 같은 값을 넣어야 프론트 로그인 토큰으로 호출할 수 있다.
- 평가 1회에 약 20회의 API 호출을 쓴다. 하루 한도(100회)를 고려해 실행한다.

---

## 추가 작업: Groq(`GROQ_API_KEY`) 성능 비교

K-EXAONE과 같은 golden 20문항으로 Groq에서도 비슷한 성능이 나오는지 측정했다.

- `LLM_PROVIDER=groq` 공급자 추가(OpenAI 호환, `https://api.groq.com/openai/v1`). `GROQ_MODEL`로 모델을 고른다(코드 기본값 `openai/gpt-oss-120b`, 로컬 `.env`에는 `qwen/qwen3.8-27b`가 지정돼 있어 이 모델로 측정).
- `evals.run_eval`에 `--provider`, `--model` 옵션 추가. 응답의 `reasoning` 필드도 읽도록 보강.

### 결과 (qwen/qwen3.8-27b, `reasoning_effort=high`)

| 구분 | 결과 |
| --- | --- |
| 1차 (연속 호출) | 70% (14/20) — 6건이 모델 한도 429로 **측정 불가** |
| 429 난 6문항 재측정 (요청 간격 60초) | 5건 정답, `lookup-04`는 끝내 429 |
| 종합 | 측정된 19문항 모두 정답 (19/19), 1문항 미측정 → 최저 95%, 한도 문제 제외 시 100% |

- 비교 기준 K-EXAONE high: 100% (20/20). **정확도는 측정된 범위에서 동일**하다.
- 실패 원인은 SQL 품질이 아니라 **Groq 무료 등급 한도**다: 이 모델은 분당 출력 토큰 1,000개(OTPM)에 전체 8,000 토큰/분이다. 질문 하나가 평균 600~650 출력 토큰이라 연속 호출이 불가능하고, 응답이 길 것으로 예상되는 요청은 `Request too large`로 아예 거절된다(`lookup-04`는 재시도해도 동일).
- 지연은 비교할 수 없다. 1차 실행은 429 재시도 대기가, 재측정은 60초 요청 간격이 지연에 섞여 있다. 생성 속도 자체는 이 실험으로 측정하지 못했다.
- 측정된 문항의 평균 출력 토큰은 644(추론 571)로 K-EXAONE(944/827)보다 적지만, 어려운 문항이 한도로 빠져 평균이 낮게 나왔을 가능성이 있어 직접 비교하지 않는다.
- 같은 `.env`의 Groq 키로 `openai/gpt-oss-120b`(추론 모델, 한도가 다를 수 있음)는 측정하지 않았다.
- 리포트: `agent/evals/reports/20261111-1052-golden_sql-qwen_qwen3_8-27b-high.md`(1차), `…-1100-…-high-retry.md`(재측정)

### 정정: gpt-oss-120b 측정 (Groq)

위에서 `gpt-oss-120b`를 "한도가 다를 수 있어 측정하지 않았다"고 적었다. 공식 한도(RPM 30, RPD 1K, TPM 8K, TPD 200K)는 qwen3.8과 같지만, qwen에서 실제로 막힌 건 문서에 없던 출력 토큰 한도(OTPM 1,000)였다. `gpt-oss-120b`에서는 응답 헤더에 별도 출력 한도가 보이지 않았고 실제로 20문항이 429 없이 끝났다(요청 간격 15초).

| 모델 (Groq) | 정확도 | 429 | 평균 출력 토큰(추론) |
| --- | --- | --- | --- |
| qwen/qwen3.8-27b | 19/19 측정 + 1문항 측정 불가 | 6건(재측정 후 1건 잔존) | 644 (571) |
| openai/gpt-oss-120b | 95% (19/20) → guard 수정 후 100% | 0건 | 1,114 (992) |

- `compare-04`는 모델 오류가 아니라 **guard 오탐**이었다. 모델이 `events` 조인의 `ON` 절에 `timestamp` 기간 조건을 넣었는데 guard가 `WHERE`만 검사해 거부했다. `WHERE`와 `JOIN … ON` 조건을 모두 보도록 고치고 테스트 2건을 추가했다(`pytest` 90건 통과). 수정 후 재측정은 새로 생성한 SQL 기준으로 통과했다.
- 이 모델이 만든 SQL에는 `events` 첫 CTE에 하한 없이 `timestamp < current_date`만 있는 것도 있었다. guard는 비교 조건이 하나라도 있으면 통과시키므로 풀스캔 방지는 EXPLAIN 비용 상한에 의존한다. Phase 4에서 하한 조건까지 요구할지 검토한다.
- 평가 지연(13~30초)은 요청 간격(15초)이 섞여 있어 생성 속도로 읽을 수 없다. 단건 호출은 64토큰이 0.13초로 K-EXAONE보다 훨씬 빠르다.
- 리포트: `agent/evals/reports/20261111-1111-golden_sql-openai_gpt-oss-120b-high.md`, `…-1117-…-recheck.md`

---

## 모델 선택 결론과 향후 방향

### 결론

**Phase 2 개발은 Groq `openai/gpt-oss-120b`로 진행한다.** 최종 모델은 Phase 4 평가 후 확정한다. 공급자는 `LLMClient` 한 곳에서 바꿀 수 있어 지금 선택은 되돌릴 수 있다.

| 항목 | K-EXAONE 2.5 | Groq gpt-oss-120b | Groq qwen3.8-27b |
| --- | --- | --- | --- |
| golden 20문항 정확도 | 100% | 100% (guard 수정 후) | 19/19 측정, 1문항 측정 불가 |
| 단건 생성 속도 | 약 45 tok/s | 약 480 tok/s (64토큰 0.13초, 1회 측정) | 측정 안 함 |
| 한도 | 하루 100회, 초당 1회 | RPM 30 / RPD 1K / TPM 8K / TPD 200K | 위와 같고 **분당 출력 1,000토큰**이 추가로 걸림 |
| tool calling | 문서에 요청 파라미터 설명 없음(미확인) | 도구 호출 → 결과 반영 → 답변 왕복 확인 | 측정 안 함 |

선택 이유

- **Tool calling**: Phase 2의 핵심 요건이다. gpt-oss는 확인했고, K-EXAONE은 API 문서에 `tools` 요청 파라미터 설명이 없다.
- **속도**: 루프를 여러 번 도는 구조라 생성 속도 차이가 지연에 그대로 곱해진다. K-EXAONE은 compare 문항이 45~74초 걸렸다.
- **정확도**: 같은 20문항에서 동일하다. 다만 이 문항셋은 지표 정의를 프롬프트에 넣어 둔 쉬운 문항이 대부분이라 **모델 간 정확도 차이를 가리지 못한다.** 정확도는 선택 근거가 아니다.
- qwen3.8-27b는 분당 출력 1,000토큰 한도로 연속 호출이 어려워 제외한다.

### 주의: 하루 토큰 한도(TPD 200K)

"하루 호출 횟수 제한이 없다"는 것이 장점이 아니다. 질문 하나(SQL 생성)가 평균 약 3,000토큰(입력 1,860 + 출력 1,114)이라 **하루 약 65문항**이고, 평가 20문항 한 번이 하루 한도의 약 30%다. Phase 2 Tool Loop는 호출이 최대 15회이고 대화 이력이 누적돼 질문당 수만 토큰이 들 수 있다. 무료 등급 그대로는 개발·평가를 하루 몇 번 돌리기도 빠듯할 수 있다.

### 향후 방향

1. **Phase 2 착수 전**: `OpenAICompatClient`에 `tools` 전송과 `tool_calls` 응답 파싱을 추가한다. 이번에 확인한 것은 도구 1개, 단일 호출뿐이므로 다중 도구, 한 응답의 병렬 호출, 오류 결과를 보고 SQL을 고쳐 재시도하는 경우를 루프 구현 중 평가로 확인한다.
2. **토큰 예산 관리**: 실행 예산(Budget)에 누적 토큰을 반드시 넣고, 평가 실행 전 하루 소비량을 가늠한다. TPD에 닿으면 Groq 유료 등급을 검토한다(한도·요금은 아직 확인하지 않음).
3. **프롬프트 토큰 절감**: 입력 약 1,860토큰 중 스키마 요약이 대부분이다. Phase 3에서 RAG로 바꾸면 줄어들 것으로 기대하지만 이는 평가로 확인한다.
4. **평가셋 개선(Phase 4)**: 모호한 표현, 다단계 계산, `events` 드릴다운, 지표 정의를 프롬프트에 주지 않은 경우를 늘려 모델 간 변별력을 확보한다. 이때 K-EXAONE과 gpt-oss(필요하면 다른 모델)를 정확도·지연·토큰·비용으로 다시 비교해 최종 모델을 정한다.
5. **풀스캔 방지 보강(Phase 4 검토)**: guard는 `events`에 기간 비교 조건이 하나라도 있으면 통과시킨다. gpt-oss가 하한 없이 `timestamp < current_date`만 둔 CTE를 만들었으므로, 하한 조건까지 요구할지 정한다. 지금은 EXPLAIN 비용 상한과 5초 타임아웃이 방어한다.
6. **기본값 정리**: `.env`의 `LLM_PROVIDER`와 `GROQ_MODEL`을 gpt-oss-120b로 맞추는 것은 Phase 2 착수 시 함께 한다(현재 로컬 `.env`는 `GROQ_MODEL=qwen/qwen3.8-27b`).
