# LLM 분석 에이전트 Phase 2: Tool Loop와 실행 예산

## 요청

`docs/plans/01-text_to_sql_LLM_분석_에이전트_구현_계획.md`의 Phase 2 구현.
계획 문서는 Claude tool use 기준이지만, Phase 1 결론에 따라 **Groq `openai/gpt-oss-120b`(OpenAI 호환 tool calling)** 로 구현했다.

## 작업 내용

### 1. LLM 클라이언트 tool calling (`app/llm/`)

- `chat(messages, tools=, tool_choice=)` 추가. 응답의 `tool_calls`를 `ToolCall(id, name, arguments)`로 파싱한다. 인자는 JSON 문자열 그대로 두고(해석 실패도 결과로 돌려주기 위해), 객체로 오면 문자열로 바꾼다.
- `ChatResult.assistant_message()`: 대화 이력에 다시 넣을 assistant 메시지(OpenAI 형식).
- `wait_ms`: 요청 간 최소 간격·429/5xx 재시도로 기다린 시간. 실패 시 `LLMError.wait_ms`에도 남긴다.
- 하루 한도 429(`per day`, Groq TPD/RPD)는 재시도하지 않고 바로 실패시킨다.
- 기본 공급자 `exaone` → **`groq`**, Groq 요청 간격 `GROQ_MIN_INTERVAL_SECONDS=2.0`(RPM 30).

### 2. 난이도 분류와 예산 (`app/agent/router.py`, `budget.py`)

- 분류기: 같은 모델, `reasoning_effort=low`로 `{"difficulty", "reason"}` JSON 한 줄을 받는다. 해석에 실패하면 `compare`로 시작한다(`fallback: true`).
- 예산(툴 호출 / SQL 실행 / 누적 토큰 / 시간 / reasoning effort)

  | 난이도 | 툴 호출 | SQL | 토큰 | 시간 | effort |
  | --- | --- | --- | --- | --- | --- |
  | lookup | 3 | 1 | 20K | 30s | medium |
  | compare | 6 | 3 | 50K | 60s | high |
  | diagnose | 15 | 8 | 120K | 180s | high |

  - 계획의 시간(15/40/120초)은 Claude 기준이라 늘렸고, **경과 시간에서 레이트 리밋 대기는 뺀다.** 무료 등급 대기열 때문에 결론 없이 끝나지 않게 하기 위함이다(대기 시간은 `rateLimitWaitMs`로 따로 남긴다).
  - 툴 호출 수에는 `submit_report`, `request_more_budget`, 캐시된 SQL이 포함되지 않는다. SQL 수에는 DB까지 간 실행만 센다(guard 거부 제외).
- 소진 규칙
  - 툴 호출·토큰·시간·입력 크기 중 하나라도 다 차면 → 시스템 메시지 `[예산 소진]` + `submit_report`만 허용(함수 지정 `tool_choice`). 강제 호출 2회까지, 그래도 없으면 서버가 "결론을 정리하지 못했다"는 답을 만든다. 상태 `budget_exhausted`.
  - SQL 수가 다 차면 **run_sql만 도구 목록에서 뺀다**. 처음엔 이것도 소진으로 처리했더니 lookup(SQL 1회)이 정상적으로 SQL을 1번 실행하자마자 `budget_exhausted`가 됐다.
  - 80%에 처음 닿으면 `[예산 안내]` 시스템 메시지를 한 번 넣는다.
- 승격: `request_more_budget`으로 1회 상위 난이도 예산으로 바꾼다. 사용량·경과 시간은 이어진다.

### 3. 도구 (`app/agent/tools/`)

| 도구 | 동작 |
| --- | --- |
| `run_sql` | guard → 실행. 실패(guard 거부·DB 오류·타임아웃·비용 초과)는 사유를 결과로 돌려줘 모델이 고치게 한다. 성공 시 `step_id`를 돌려준다. 같은 SQL(공백 정규화)은 원래 step 결과를 다시 보여 주고 예산을 차감하지 않는다. 모델에게는 20행·유효숫자 6자리만, 실행 로그에는 200행·원본 값을 남긴다 |
| `describe_table` | 화이트리스트 테이블만. `information_schema` 컬럼·타입(캐시) + 최근 샘플 3행(RLS 적용, `events`는 최근 1일 조건) + 한 줄 설명 |
| `submit_report` (`final_answer.py`) | `summary`, `findings[{claim, evidence[step_id]}]`, `chart{type: bar/line, step_id, x, y[]}` |
| `request_more_budget` | 승격 요청 (승격 가능할 때만 도구 목록에 노출) |

- **근거 연결 검증**: 각 finding의 evidence는 성공한 `run_sql` step이어야 한다. 근거 없음·실패한 step·없는 step을 인용하면 사유와 인용 가능한 step 목록을 돌려주고 다시 받는다(2회). 그 뒤에는 근거 없는 주장을 빼고 받아들이며 `droppedFindings`에 개수를 남긴다. chart의 x/y는 해당 step 결과 컬럼이어야 한다.
- `search_knowledge`는 계획상 Phase 3(RAG)에서 연결한다. Phase 2는 Phase 1과 같이 스키마 요약을 시스템 프롬프트에 넣는다.

### 4. Tool Loop (`app/agent/loop.py`)

- `AgentLoop.run()`이 이벤트를 내는 async generator다: `started → classified → (tool_call → tool_result)* → answer → done`, 오류 시 `error → done`. `out_of_scope`는 도구 없이 `rejected`로 끝난다.
- 루프의 `tool_choice`는 항상 `required`다. `auto`에서는 gpt-oss가 도구 없이 빈 응답으로 끝내는 경우가 있었다. 그래도 텍스트만 오면 한 번 안내하고, 두 번째는 `submit_report`를 강제한다.
- 공급자 `tool_use_failed`(400)는 안내 메시지를 넣고 연속 3회까지 재시도한다.
- **입력 크기 관리**: 오래된 도구 결과를 단계적으로 줄인 사본을 보낸다(원본 이력은 유지).
  - level 0: 최근 2개 외 결과 rows → 5행 / level 1: 최근 2개 외 rows 제거 + 지난 SQL 인자 앞 160자만 / level 2: 최근 1개만 남기고 level 1
  - `AGENT_MAX_PROMPT_TOKENS`(기본 4,800)를 넘으면 다음 단계로 줄이고, level 2로도 넘거나 공급자가 413을 주면 입력 소진으로 보고 결론을 강제한다. 토큰 추정은 직전 호출의 `문자 수 / prompt_tokens` 비율로 보정한다.
- 실행 로그 저장 실패(DB 다운 등)는 답변을 막지 않는다. 스트림이 중간에 닫히면 `failed`로 기록한다.
- 안전 상한: 실행당 LLM 호출 30회.

### 5. 실행 로그 (`app/agent/store.py`)

- `klicklab_agent` 롤 연결(동기 풀 + `asyncio.to_thread`)로 `agent_runs` 생성 → 난이도 → step마다 `agent_steps` → 종료 시 상태·답변·툴 호출 수·토큰·지연을 저장한다.
- 이 테이블에는 RLS가 없으므로 조회는 항상 토큰의 `sdk_key` + `user_id`로 제한한다. 응답 키는 camelCase.
- `cost_usd`는 아직 비워 둔다(공급자 단가 미확정). step별 토큰은 한 LLM 응답에 도구 호출이 여러 개일 수 있어 남기지 않았다(V4 스키마 변경 없음).

### 6. API (`app/api/runs.py`)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/agent/runs` | `{question}` → SSE (`event: <type>` / `data: <json>`) |
| `GET` | `/agent/runs?limit=` | 내 실행 목록 |
| `GET` | `/agent/runs/{id}` | 실행 상세 + steps |
| `POST` | `/agent/runs/{id}/feedback` | `{feedback: 1 \| -1, note}` → 204 |

- SSE는 `sse-starlette` 없이 `StreamingResponse`로 직접 만들었다(이벤트 형식이 단순해 의존성을 늘리지 않음).
- Phase 1 `POST /agent/ask`는 기준선 비교용으로 그대로 둔다.

## 실측에서 발견한 문제 (Groq gpt-oss-120b 무료 등급)

### `final_answer`라는 도구 이름을 gpt-oss가 부르지 않는다

- 도구 결과를 받은 뒤 추론에 "Need final answer."라고 쓰고 **빈 응답으로 끝냈다**(`auto`: 빈 `stop`, `required`: `tool_use_failed: model did not call a tool`). harmony 형식의 `final` 채널과 이름이 겹친 것으로 보인다.
- 같은 대화로 이름만 바꿔 비교: `final_answer` 0/3, `submit_report` 3/3, `answer` 3/3. → 모델에게는 **`submit_report`** 로 노출한다(코드 모듈명은 계획대로 `final_answer.py`).
- `submit_report`에서도 도구 이름을 `commentary`/`json`으로 내보내는 형식 오류가 가끔 있어 재시도로 처리한다.

### 무료 등급 한도가 diagnose를 막는다

| 실행 | 결과 | LLM 호출 | 입력/출력 토큰 | 지연 (레이트 리밋 대기) |
| --- | --- | --- | --- | --- |
| lookup "어제 방문자 수는?" | 정답(575명, 근거 step 1) — 형식 오류 2회 후 성공 | 4 | 5,242 / 550 | 55.8s (대부분 대기) |
| compare "지난주 대비 이번 주 유입 채널별 전환율 변화" (이름 변경 후) | **succeeded**, 채널별 finding + 막대 차트, 형식 오류 0 | 2 | 6,023 / 5,048 | 53.4s (40.3s) |
| diagnose "지난주 대비 이번 주 참여도가 떨어진 페이지와 원인" | 3회 모두 `failed` | 4~7 | 최대 20,576 / 10,022 | 37~267s |

- diagnose 실패 원인: SQL 2~5회 뒤 요청 하나가 **TPM 8K를 넘어 413**(Requested 8,971 / 9,746). 마지막 시도는 압축·강제 결론을 넣은 뒤였지만 **하루 토큰 한도(TPD 200K)** 에 걸려 중단됐다. 오늘 실측은 여기서 멈췄다.
- 요청 덤프로 확인한 실제 입력은 문자 수 / 3.3 정도(호출 4: 13,180자 → 4,090토큰)인데, 413/429 메시지의 `Requested`는 그보다 약 4,096(당시 `max_tokens`)만큼 컸다. 다만 `reasoning_effort=low` + 작은 도구 1개로 한 실험에서는 4,182 + `max_tokens` 4,500 요청이 통과해 **확정하지 못했다.** 일단 `max_tokens`가 요청 크기에 더해진다고 보고 `AGENT_STEP_MAX_TOKENS=3072`, `AGENT_MAX_PROMPT_TOKENS=4800`(합 7,872)으로 두었다.
- 시스템 프롬프트 + 도구 스키마만 약 2,400토큰이라, 상한 4,800이면 diagnose는 SQL 3~4회 뒤 압축·강제 결론 단계로 들어간다. **diagnose를 제대로 돌리려면 Groq Dev Tier 이상이나 다른 공급자가 필요하다.**

## 검증

- `ruff check`, `ruff format --check` 통과
- `pytest` **146건 통과**(Phase 1 90건 + 56건)
  - LLM 클라이언트: 도구 전송·`tool_calls` 파싱, 대기 시간 기록, 하루 한도 429 미재시도
  - 예산·분류: 소진 조건(툴 호출/토큰/시간/입력), SQL 소진은 run_sql만 제외, 대기 시간 제외, 80% 경고 1회, 승격 1회, 분류 파싱·fallback
  - 도구: guard 거부 시 미실행, DB 오류 피드백, 같은 SQL 캐시, 결과 행·소수 축약, 근거 검증(없음/실패 step/없는 step), 차트 컬럼 검증, 거부 후 수용, describe 화이트리스트·캐시
  - 루프(가짜 LLM): 정상 흐름과 이벤트 순서, 오류 후 자가 수정, 잘못된 근거 거부 후 수정, 예산 소진 시 강제 결론, 강제 결론 실패 시 서버 요약, out_of_scope, `tool_use_failed` 재시도/포기, 413 → 압축 이력으로 강제 결론, 텍스트 응답 안내 → 강제, 승격, 저장소 장애 시 진행, 스트림 중단 시 `failed`, 입력 상한, 이력 압축 단계
  - API: SSE 이벤트 형식, 인증, 목록·상세·피드백, 실행 로그 저장 통합 테스트(로컬 DB가 있을 때만: 저장·조회 왕복, 다른 sdk_key 차단)
- 라이브: 위 표의 lookup·compare 성공, `agent_runs`/`agent_steps` 적재 확인
- **확인하지 못한 것**: diagnose 질문 성공(무료 등급 한도), 압축·입력 상한 로직의 실제 API 동작, uvicorn 위 SSE 종단 호출(TestClient로만 확인), 실제 SQL 오류에 대한 자가 수정(가짜 LLM으로만 확인)

## 참고

- 로컬 DB `agent_runs`에 개발 중 실행 7건과 통합 테스트 행(`sdk_key=test-store-key`)이 남아 있다. `klicklab_agent` 롤에는 DELETE 권한이 없어 테스트가 지우지 못한다.
- `agent/.env`에 `LLM_PROVIDER`가 없으므로 이제 코드 기본값 `groq`가 적용된다. `.env.example`을 Phase 2 기준으로 갱신했다.

### 다음에 할 일

1. TPD가 풀린 뒤 diagnose 질문으로 압축·입력 상한 동작을 확인하고, `Requested`에 `max_tokens`가 더해지는지(effort high + 도구 여러 개) 다시 실험한다.
2. diagnose가 무료 등급에서 계속 막히면 Groq Dev Tier 또는 다른 공급자(Claude 등)로 Phase 2 루프를 측정한다. `LLMClient`만 교체하면 된다.
3. Phase 4 평가 전에 golden 20문항을 루프로도 돌려 Phase 1(단일 턴) 대비 정확도·토큰·지연을 비교한다. 문항당 LLM 호출 3회 이상이라 한 번에 하루 한도의 상당 부분을 쓴다.
