# 로컬 LLM 폴백 Phase 1~4: local 공급자, FallbackLLMClient, 화면 연동, 평가

## 요청

`docs/plans/02-로컬_LLM_폴백_도입_계획.md`의 Phase 1부터 4까지 진행.

## 작업 내용

### Phase 1. `local` 공급자

- `Settings`에 `LOCAL_*` 추가(`app/config.py`). 기본 모델은 Phase 0에서 만든 파생 모델 `gpt-oss-20b-ctx32k`, `LOCAL_NUM_CTX=32768`.
- `build_llm_client`를 공급자별 `build_provider_client`로 나누고 `local` 분기를 추가했다(`app/llm/__init__.py`).
- `OpenAICompatClient`(`app/llm/openai_compat.py`)에 추가한 것:
  - `drop_params`, `param_map`: 공급자별 파라미터 제거·이름 변경. 로컬은 gpt-oss 계열이 아니면 `reasoning_effort`를 보내지 않는다.
  - `max_retry_wait`: `retry-after`가 상한보다 길면 기다리지 않고 바로 실패한다(폴백용). 기본값 `None`이라 기존 동작은 그대로다.
  - `max_concurrency`: 세마포어. 기다린 시간은 `wait_ms`에 넣는다.
  - `context_window`: `prompt_tokens`가 컨텍스트 창의 98%에 닿으면 잘림 의심 경고를 남긴다.
  - `max_reasoning_effort`: 추론 강도 상한(로컬 기본 `medium`, Phase 4 결과로 추가).
  - Ollama의 `500 "error parsing tool call"`을 `400 (tool_use_failed)`로 바꾼다. 모델 출력 문제를 서버 장애로 보지 않고, 루프의 기존 형식 재시도 경로를 타게 하려는 것이다(Phase 4 결과로 추가).
  - 공급자 특성 속성 `provider`, `time_factor`, `forced_tool_unreliable`와 `session()`(자기 자신 반환).
- `LLMError`에 `retry_after`, `daily`, `unavailable`(연결 실패), `ChatResult`에 `provider`, `model`, `fallback`을 추가했다.
- 시작 시 로컬 서버 점검(`app/llm/health.py`): `/v1/models`에 모델이 있는지 확인하고, Ollama라면 `/api/show`의 `num_ctx`가 `LOCAL_NUM_CTX`보다 작은지 본다. 실패해도 서버는 뜨고 경고만 남긴다(`main.py` lifespan).

### Phase 2. `FallbackLLMClient` (`app/llm/fallback.py`)

- 클라이언트 목록을 순서대로 시도하는 체인이다. 폴백 대상은 `LLM_FALLBACK_STATUSES`(기본 429, 413, 5xx)와 연결 실패이고, 401/403/400/408은 그대로 낸다.
- 쿨다운: 실패한 공급자를 `retry-after`(없으면 60초, 하루 한도면 3600초) 동안 건너뛴다. 413은 요청 크기 문제라 쿨다운을 걸지 않는다.
- 실행 내 고정: `session()`이 `FallbackSession`을 돌려주고, 한 번 넘어가면 실행이 끝날 때까지 그 공급자를 쓴다. 쿨다운 중에 시작한 실행은 처음부터 폴백으로 간다.
- 대체 공급자도 실패하면 첫 공급자의 원래 오류를 낸다(로컬 서버가 꺼져 있으면 "LLM 사용 한도에 도달했습니다").
- 폴백이 있을 때 기본 공급자는 재시도 1회, 대기 상한 5초(`LLM_PRIMARY_MAX_RETRIES`, `LLM_PRIMARY_MAX_WAIT_SECONDS`)이고, 대체 공급자는 재시도하지 않는다.
- 루프 연동(`app/agent/loop.py`, `router.py`, `budget.py`):
  - 실행 시작 시 `open_session()`으로 세션을 받아 분류와 모든 단계 호출에 쓴다.
  - `Budget.time_factor`: 현재 공급자의 `time_factor`(로컬 2.0)를 시간 한도와 호출 시간 제한에 곱한다.
  - 로컬 한정 보정: 결론 강제 단계에서 다른 도구를 부르면 `FINAL_ONLY_RETRY` 메시지를 넣고 강제 횟수에서 빼서 다시 요청한다(최대 2회). `forced_tool_unreliable`가 없는 공급자는 기존과 같다.
- 단위 테스트 `tests/test_llm_fallback.py` 35건: 429/413/5xx 폴백, 401/403/400/408 비폴백, `retry-after` 상한 초과 시 대기 없이 폴백, 쿨다운과 복귀, 하루 한도의 긴 쿨다운, 실행 내 고정, 로컬 다운 시 원래 오류 문구, 동시성 제한, 설정 조립, 헬스 체크, 루프 통합(실행 중 전환 시 tool_calls 이력 이어짐, 분류 단계 폴백, 결론 강제 보정), 추론 강도 상한, Ollama 도구 해석 오류 변환.

### Phase 3. 실행 기록·화면·평가 연동

- 실행 요약(`done`)에 `model`, `models`(모델별 호출 수), `fallbackCalls`, `primaryError` 추가. 전환 시점에 `fallback` 이벤트(`provider`, `model`, `primaryStatus`)를 한 번 내고 경고 로그를 남긴다. DB 마이그레이션은 하지 않았다(계획 9장).
- 프론트엔드: `fallback` 이벤트를 받으면 난이도 줄 옆에 "로컬 모델" 표시를 붙인다(`TurnView.tsx`). 스트림 응답 직후에만 보이고, 지난 대화를 다시 열면 보이지 않는다.
- 평가 러너: 기본으로 `LLM_FALLBACK_PROVIDER=none`을 강제하고 `--fallback`으로만 켠다. `--provider local`을 지원한다. Tool Loop·분석 보고서는 여러 모델이 섞였거나 폴백 실행이 있으면 머리에 경고를 남긴다(`report.model_mix_warning`).
- `.env.example`에 로컬·폴백 설정과 파생 모델 만드는 법을 적었다.

### Phase 4. 품질·지연 평가

같은 20문항(lookup-01~14, compare-01~06)을 Tool Loop로 돌렸다. 로컬 `gpt-oss-20b-ctx32k`, prompt 모드.

| 구성 | 실행 정확도 | lookup / compare | 지연 평균 / 중앙값 / 최대 (ms) | 예산 소진 |
| --- | --- | --- | --- | --- |
| Groq `gpt-oss-120b` 단독 | 평가 불가 (2/20만 응답, 18건 TPD 429) | - | - | - |
| 로컬 단독, 추론 강도 그대로 (high) | 90.0% (18/20) | 92.9% / 83.3% | 33,659 / 20,656 / 151,015 | 5.0% |
| 로컬 단독, 상한 medium | **95.0% (19/20)** | 100% / 83.3% | 24,299 / 21,577 / 74,875 | 5.0% |
| 참고: 단일 턴 Groq / 로컬 (Phase 0) | 95.0% / 95.0% | | 16,819 / 23,712 (평균) | |

- high에서는 compare 단계 응답 15건이 `finish=length`였다. 추론만으로 `AGENT_STEP_MAX_TOKENS`(3072)를 다 써서 도구 호출 없이 끝났다. 상한을 medium으로 두자 정확도가 오르고 최대 지연이 절반으로 줄었다.
- Groq 단독 Tool Loop는 오늘 하루 토큰 한도(200K)가 이미 소진돼 측정하지 못했다. 그 자체가 폴백이 필요한 상황의 실례다.

**폴백 시나리오** (golden 44문항, Groq 기본 + 로컬 폴백, 실행마다 기본 공급자의 2번째 호출에 모의 429 주입. Groq 한도가 소진된 상태라 대부분은 첫 호출의 실제 TPD 429로 넘어갔다)

| | 보정 전 | 보정 후 (상한 medium + 도구 해석 오류 변환) |
| --- | --- | --- |
| 실행 완주 (succeeded) | 37/44 (실패 3, 예산 소진 4) | **44/44** |
| 실행 정확도 | 79.1% (34/43) | 81.8% (36/44) |
| 실행 중 Groq → 로컬 전환 | 12건 (완주 11) | 10건 (완주 10, 정답 9) |
| 지연 평균 lookup / compare (ms) | 26,278 / 66,236 | 21,837 / 26,572 |

- 보정 전 실패 3건은 모두 Ollama가 모델의 잘못된 도구 호출 JSON에 500을 낸 경우였다. 폴백 체인이 이를 서버 장애로 보고 "사용 한도" 문구로 실패시켰다. 400 `tool_use_failed`로 바꾼 뒤에는 형식 재시도로 이어져 7건 모두 완주했다.
- 로컬 서버를 끈 상태(포트 9): 헬스 체크가 연결 실패를 경고하고, 한도 초과 시 "LLM 사용 한도에 도달했습니다" 문구로 끝났다(2/2). 서버 기동(`/agent/health`)은 로컬 서버 유무와 관계없이 정상이다.

**원인 분석** (analysis 12문항, 로컬 단독, 규칙 채점만): 통과 41.7% (5/12), 정답 사실 언급률 37.5%, 평균 주장 0.7개(근거 검증에서 뺀 주장 11개), 지연 평균 63.7초. 분류기가 diagnose 질문 12개 중 6개만 diagnose로 분류했다. Groq 기준선은 diag-01 한 문항(0/1, 378초)뿐이라 비교할 수 없다.

### 결정

- **폴백 허용 난이도: 전체 허용**으로 둔다. lookup·compare는 로컬 단독 정확도가 단일 턴 Groq와 같은 수준이다. diagnose는 품질이 낮지만(근거 인용 형식 오류로 주장이 대부분 빠짐), 개발 환경 전용이고 응답에 폴백 표시가 붙는다. 또 "한도 안내만 하고 끝내기"보다는 요약이라도 주는 편이 낫다고 봤다. Groq 기준선이 생기면 다시 판단한다.
- `LOCAL_TIME_FACTOR=2.0`을 유지한다. 보정 후 시나리오의 최대 지연은 lookup 62초, compare 49초로 배율 적용 한도(60/120초) 안이다.
- `max_prompt_tokens` 완화(계획 3.5)는 하지 않는다. 로컬 입력은 평균 약 11K 토큰으로 32K 창 안이고, 압축 때문에 실패한 사례가 없었다.

## 검증

- `pytest` 291건 통과(신규 35건), `ruff check`·`ruff format --check` 통과.
- 프론트엔드 `tsc --noEmit -p tsconfig.app.json`, `eslint src/components/agent` 통과.

## 보고서

- `agent/evals/reports/20261112-1428-golden_sql-gpt-oss-20b-ctx32k-loop-phase1-local.md`
- `agent/evals/reports/20261112-1428-golden_sql-openai_gpt-oss-120b-loop-phase4-groq.md`
- `agent/evals/reports/20261112-1512-golden_sql-gpt-oss-20b-ctx32k-loop-phase4-local-medium.md`
- `agent/evals/reports/20261112-1538-analysis-gpt-oss-20b-ctx32k-phase4-local.md`
- 폴백 시나리오 점검 스크립트는 임시 폴더에서만 썼고 저장소에는 넣지 않았다.

## 후속

- Groq 한도가 풀리면 같은 20문항 Tool Loop와 analysis를 Groq 단독으로 돌려 로컬과 비교한다.
- diagnose 로컬 품질: 근거 인용 형식(`evidence: [2, "step_id"]` 같은 출력)과 diagnose 분류 누락을 개선한다.
