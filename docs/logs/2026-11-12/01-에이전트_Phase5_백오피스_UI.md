# LLM 분석 에이전트 Phase 5: 백오피스 UI

## 요청

`docs/plans/01-text_to_sql_LLM_분석_에이전트_구현_계획.md`의 Phase 5 구현. 백엔드(FastAPI)는 Phase 2에서 만든 `/agent/runs` API를 그대로 쓰고, 프론트엔드만 추가했다.

## 작업 내용

### 1. 라우팅·진입점

- `Dashboard.tsx`: `/dashboard/agent` 라우트, 헤더 제목·설명 추가
- `Sidebar.tsx`: "분석 에이전트" 탭(Sparkles 아이콘)을 리포트 앞에 추가
- `vite.config.ts`: 개발 서버 프록시 `/agent` → `http://localhost:8000`

### 2. 화면 (`frontend/src/components/agent/`)

| 파일 | 역할 |
| --- | --- |
| `types.ts` | `RunView`(화면 상태), `Step`, `Answer`, `RunSummary` |
| `api.ts` | 실행 목록·상세·피드백 호출, `POST /agent/runs` SSE 스트림 파서 (`fetch` + `ReadableStream`, 인증 헤더 때문에 `EventSource` 대신 사용) |
| `AgentDashboard.tsx` | 좌측 기록 + 중앙 질문·답변, 이벤트 → 상태 반영, 중단·피드백 |
| `RunHistory.tsx` | 실행 기록 목록(상태 점, 질문, 시각, 피드백), 새 질문 |
| `StepList.tsx` | 접을 수 있는 실행 단계: 툴 호출 한 줄 요약 → 펼치면 SQL, 결과 표, 오류 |
| `ResultTable.tsx` | 결과 표(최대 50행 표시, 전체 행 수 표기) |
| `AnswerChart.tsx` | 답변의 `chart` 스펙을 근거 step의 결과로 렌더링 |

- 실시간 실행과 기록 조회가 같은 `RunView` 모양을 쓴다. SSE 이벤트(`started`, `classified`, `tool_call`, `tool_result`, `answer`, `error`, `done`)는 `applyEvent`가 상태에 쌓고, 기록은 `GET /agent/runs/{id}`를 같은 모양으로 변환한다.
- 답변의 finding 뒤에 근거 step 번호 버튼이 붙고, 누르면 실행 단계를 펼쳐 해당 step으로 스크롤한다.
- 차트: `line`은 `HorizontalLineChart`(x 컬럼을 `date` 키로), `bar`는 `HorizontalBarChart`(y 컬럼마다 하나). x·y 컬럼이 결과에 없으면 그리지 않는다.
- `submit_report` step은 답변 자체이므로 실행 단계에서 숨긴다.
- UI 규칙에 따라 보조 설명 문구 없이 구조로 전달했다: 빈 화면은 "질문을 입력하세요" 한 줄, 난이도·예산 소진은 작은 한 줄, 단계는 접힘 구조.
- 입력창: Enter 전송 / Shift+Enter 줄바꿈(한글 조합 중에는 무시), 500자 제한(서버 제한과 동일), 실행 중에는 중단 버튼(`AbortController` → 서버는 연결 끊김을 실패로 기록).
- 피드백: 👍/👎. 서버에 취소 API가 없어 이미 선택한 값을 다시 누르면 무시한다. 실패하면 이전 값으로 되돌린다.

## 검증

- `tsc -b`, `eslint src/components/agent` 오류 없음
- `npm run build` 성공
- **실제 화면·SSE 동작은 확인하지 못했다.** 로컬 agent 서버와 vite 서버 기동 명령이 자동 승인되지 않아 브라우저에서 질문을 보내 보지 못했다. 아래 항목은 코드 읽기만으로 작성했고 실행 확인이 필요하다.
  - SSE 파서가 실제 스트림(`event:`/`data:` 블록)을 제대로 나누는지
  - 인증 토큰 만료(15분) 시 `/agent/*` 호출은 401 후 갱신하지 않는다(다른 화면이 쓰는 방식과 같은 `getToken()` 직접 사용)
  - 좌측 기록·중앙 영역 높이(`h-[calc(100vh-148px)]`)가 헤더와 맞는지
  - 선 그래프의 x축이 날짜가 아닌 값일 때 `HorizontalLineChart` 표시

## 남은 것

- 프론트엔드 자동 테스트 환경이 없어 SSE 파서·`applyEvent` 단위 테스트는 작성하지 않았다.
- 실행 중 새로고침하면 진행 중이던 화면은 사라지고 기록 목록에서만 볼 수 있다(서버는 계속 실행하지 않고 연결 끊김으로 실패 처리).

---

## 추가 작업: 실행 후 확인한 내용과 오류 메시지 정리

### 실행 확인 (agent 서버 기동 후, vite 프록시 경유)

- 데모 계정 토큰으로 `POST /agent/runs`("어제 방문자 수는?")가 SSE 이벤트를 순서대로 내려줬고(`started → classified → tool_call/tool_result → answer → done`), 목록·상세·피드백(204) API도 정상이었다.
- 브라우저 화면 렌더링(레이아웃, 접힘, 근거 이동, 차트)은 직접 확인하지 못했다.

### LLM 오류 원문이 화면에 노출되던 문제

Groq 일일 토큰 한도(429)에 걸렸을 때 `LLM 호출 실패: LLM 응답 오류 429: {"error":{"message":"... organization `org_...` ..."}}` 원문(조직 ID 포함)이 그대로 표시됐다. 서버가 공급자 응답 본문을 SSE `error` 이벤트와 `/agent/ask`의 502 응답에 그대로 실었기 때문이다.

- `LLMError.user_message`(`app/llm/base.py`): 상태 코드별 사용자용 문구(429 한도, 408 지연, 401/403 인증, 그 외 일반). 원문은 서버 로그(`log.warning`)에만 남긴다.
- `loop.py`의 `error` 이벤트와 `ask.py`의 502 응답이 `user_message`를 쓴다.
- 프론트(`api.ts`의 `errorMessage`): 서버에 연결하지 못했을 때 브라우저 원문("Failed to fetch") 대신 "에이전트 서버에 연결할 수 없습니다.", 401은 로그인 만료 안내.
- 테스트 248건 통과(원문·조직 ID가 메시지에 없는 테스트 추가), ruff, `tsc`, eslint 통과.
- 평가 코드는 오류 문구가 아니라 오류 유무로 공급자 오류를 판단하므로 영향이 없다.
- 실행 중인 agent 서버는 코드를 다시 읽지 않으므로 재시작해야 반영된다.

## 추가 작업: 멀티턴 대화

### 문제

같은 화면에서 추가 질문을 보내면 새 대화가 만들어졌다. 질문마다 독립된 실행(run)이었고, 화면은 질문 하나만 들고 있었으며, 에이전트도 이전 질문·답변을 모델에 전달하지 않았다. 그래서 "그럼 지난주는?" 같은 후속 질문은 맥락이 없었다.

### 변경

- **DB** `V6__agent_conversations.sql`: `agent_runs.conversation_id`(NOT NULL, 기본 `gen_random_uuid()`) + 인덱스. 기존 실행은 각각 하나의 대화(`conversation_id = id`). 라이브 DB에서 트랜잭션 후 롤백으로 문법·기존 37행 백필을 확인했다(적용은 백엔드 재시작 시 Flyway가 한다).
- **저장소** (`store.py`)
  - `resolve_conversation`: 요청의 `conversationId`가 이 사용자(sdk_key + user_id)의 대화면 그 id와 최근 3턴(질문 + 최종 답변 요약, 성공·예산 소진 건만), 아니면 새 id와 빈 이력. 남의 id를 넣어도 이력이 새지 않는다.
  - `list_conversations`(제목 = 첫 질문, 실행 수, 마지막 시각·상태), `get_conversation`(실행들을 오래된 순서로, 단계 포함).
- **에이전트** (`loop.py`, `prompts.py`, `router.py`, `turn.py`)
  - 분류기에 이전 질문들을, 에이전트 프롬프트에 "이전 대화(참고용)" 블록(질문 200자·답변 요약 400자로 자름)을 넣는다. 이전 SQL 결과는 넣지 않아 토큰을 아낀다. 수치를 근거로 인용하지 말고 다시 조회하라고 지시한다.
  - RAG 모드의 지식 검색어에는 직전 질문을 함께 쓴다(후속 질문만으로는 문서를 못 찾음).
  - 이력이 없으면 프롬프트가 이전과 같다(평가 영향 없음). 이력 조회가 실패하면 새 대화로 진행한다.
  - SSE `started` 이벤트에 `conversationId`가 들어간다.
- **API**: `POST /agent/runs`가 `conversationId`를 받는다. `GET /agent/conversations`, `GET /agent/conversations/{id}` 추가(`/agent/runs` 계열은 유지).
- **프론트**: 한 대화의 턴들을 위아래로 쌓아 보여 준다(`TurnView`: 질문, 실행 단계, 답변·근거·차트, 피드백이 턴마다). 좌측 목록은 대화 단위("새 대화"), 대화를 고르고 질문하면 이어서 진행된다. 실행 단계는 실시간 턴만 펼친 채로 시작한다.

### 검증

- 에이전트 테스트 255건 중 253건 통과, ruff 통과. 실패 2건(`test_store_round_trip_and_scoping`, `test_store_conversations`)은 로컬 DB에 V6가 아직 적용되지 않아서이며 백엔드 재시작 후 확인해야 한다. 통과 항목: 후속 질문 프롬프트에 이전 턴 포함, 첫 질문은 이력 블록 없음, 대화 id 저장, 이력 조회 실패 시 새 대화, API가 `conversationId` 전달·대화 목록 범위.
- `tsc`, eslint, 빌드 통과. 브라우저 동작은 확인하지 못했다.

### 남은 것

- 이전 턴 수(3), 글자 수 제한은 임의 값이다. 후속 질문의 정확도를 평가셋으로 재지 않았다.
- (대화 삭제·이름 변경은 아래에서 추가했다.)

## 추가 작업: 대화 이름 변경·삭제

- **DB** `V7__agent_conversation_manage.sql`: 이름을 바꾼 대화만 제목을 두는 `agent_conversation_titles`(없으면 첫 질문이 제목), `klicklab_agent`에 `agent_runs` DELETE 권한(단계는 CASCADE). 롤백 트랜잭션으로 문법·권한을 확인했고, 적용은 백엔드 재시작 시 Flyway가 한다.
- **저장소·API**: `PATCH /agent/conversations/{id}`(`{title}`, 공백 정리·1~100자), `DELETE /agent/conversations/{id}`(실행·단계·제목 삭제). 둘 다 sdk_key + user_id가 내 대화일 때만 동작하고 아니면 404.
- **프론트**: 목록 항목에 마우스를 올리면 연필(제목 인라인 편집: Enter 저장, Esc 취소, 한글 조합 중 Enter 무시)과 휴지통(확인창) 버튼이 나온다. 실행 중인 대화는 편집·삭제할 수 없고, 선택한 대화를 지우면 새 대화 상태로 돌아간다.
- **검증**: API 테스트(이름 검증, 404, 인증 401) 통과, ruff·`tsc`·eslint·빌드 통과. DB 통합 테스트 `test_store_conversations`는 이름 변경·삭제(타 테넌트 거부, 실행·단계 삭제)까지 확인하도록 늘렸으며 V7 적용 전이라 아직 실패한다. 이 테스트는 이제 마지막에 대화를 지워 테스트 행이 남지 않는다. 브라우저 동작은 확인하지 못했다.

## 추가 작업: 실패 사유가 새로고침 후 바뀌는 문제

실행 중에는 SSE `error` 이벤트의 문구(예: LLM 한도 초과 안내)를 보여 주는데, 그 문구를 저장하지 않아서 기록을 다시 불러오면 `status = failed`일 때 화면이 만든 일반 문구("실행이 완료되지 못했습니다.")로 바뀌었다.

- `V8__agent_run_error.sql`: `agent_runs.error_message`. 공급자 응답 원문은 담지 않고 사용자에게 보여 준 문구만 저장한다.
- 에이전트: LLM 오류·내부 오류·연결 중단("실행이 중단되었습니다.") 때 사유를 `run.error`에 두고 이벤트와 `finish_run`이 같은 값을 쓴다. 실행/대화 상세 조회가 `errorMessage`를 돌려준다.
- 프론트: 기록을 불러올 때 `errorMessage`를 쓰고, 값이 없는 기존 실행만 일반 문구로 대신한다.
- 테스트: 저장되는 사유가 이벤트 문구와 같은지 확인. 적용은 백엔드 재시작(Flyway) 후이며, 이미 실패한 기존 실행은 사유가 NULL이라 일반 문구로 보인다.
