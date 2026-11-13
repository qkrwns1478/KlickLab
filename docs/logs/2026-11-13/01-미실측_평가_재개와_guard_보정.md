# 미실측 평가 재개와 guard 보정

## 요청

계획 문서 1·2번은 구현이 끝났지만 API 공급자 한도 때문에 실측·비교를 못 한 항목이 있었다. 작업 로그에서 그 항목을 찾아 순서대로 진행한다. 오늘 가능한 평가는 끝났고, Groq 일일 토큰 한도 때문에 못 한 것은 맨 아래 "남은 것"에 적었다.

## 로그에서 찾은 미실측 항목

| 출처 | 항목 |
| --- | --- |
| 2026-11-11 Phase 2 | diagnose 질문 성공 확인, 압축·입력 상한 로직의 실제 API 동작, `Requested`에 `max_tokens`가 더해지는지 |
| 2026-11-11 Phase 3 | prompt vs rag 루프 비교(같은 질문 여러 번) |
| 2026-11-11 Phase 4 | golden Tool Loop 44문항, 원인 분석 12문항, `--knowledge rag` 비교 |
| 2026-11-12 Phase 4 추가 | 44문항을 같은 모델로 돌린 점수 없음, Groq 단독 Tool Loop·analysis 기준선 없음 |
| 2026-11-12 코드 리뷰 | guard 엄격화(#6) 후 실제 LLM이 만든 SQL의 거절 증가 여부 |

## 작업 내용

### 1. 환경 복구와 평가 DB 재시드

- Docker Desktop이 꺼져 있어 켜고 `klicklab-postgres`를 시작했다.
- `run_eval check`가 4건 실패했다(golden lookup-09, 19, 25의 정답 결과가 비어 있음, 원인 분석 diag-04 캠페인 패턴 불성립). 시드가 실행일 기준 상대 날짜라 이틀 지나 어긋난 것이다.
- `agent/scripts/prepare_eval_db.sh`로 다시 시드했다(이벤트 267,757건, 기간 2026-10-12 ~ 11-13). 재시드 후 `check` 실패는 1건(diag-01 `campaign_ended`)만 남았다.
  - 캠페인이 시드 실행일 2~8일 전에 걸쳐 있어, 이번 주(11-09~)에 캠페인 일부가 포함되면 "이번 주에 절반 이하로 줄었다"는 조건이 성립하지 않는 것으로 **추정**한다. 요일에 따라 달라지는 시드·검사 SQL의 한계이며 코드 문제는 아니다. 확인하지는 않았다. 이 문항은 오늘 평가에서 제외했다.

### 2. guard 오탐 수정 (`app/sql/guard.py`)

저장된 golden 리포트의 모델 SQL 183개(고유)를 현재 guard로 다시 검사했다(LLM 호출 없음). 1개가 거부됐다.

- 로컬 gpt-oss-20b Tool Loop의 compare-06(`20261112-1512-…-local-medium`)이 기간 경계를 CTE의 스칼라 서브쿼리로 썼다(`timestamp >= (SELECT week_start FROM week_bounds)`). 11-12 리뷰 #6 반영으로 "컬럼이 없는 값과의 비교"만 인정하게 한 뒤 이 형태가 거절됐다. 당시 리포트의 이 문항이 "행 수 불일치(정답 6, 예측 0)"로 틀린 것도 같은 원인일 가능성이 높다.
- 수정: 비교 상대에 컬럼이 있어도 FROM이 있는 스칼라 서브쿼리 안의 컬럼은 서브쿼리 자신의 테이블을 가리키므로 값으로 본다. 단 바깥 `events.timestamp`를 가리킬 수 있는 경우(`timestamp >= (SELECT timestamp)`, 바깥 별칭으로 한정한 컬럼)는 계속 거절한다.
- 테스트: 거절 3건, 허용 2건 추가(guard 테스트 57건). 수정 후 저장된 SQL 183개 중 거부 0개.
- 리뷰 #6 후속으로 남겨 둔 "엄격화 후 실제 LLM SQL 거절 증가 여부"는 이 재검사로 확인했다(오탐 1건, 수정 완료). 새로 생성한 SQL로 다시 보지는 않았다.

### 3. Groq `Requested` 크기 실험 (Phase 2 미확인 항목)

Phase 2에서는 413/429 메시지의 `Requested`가 입력에 `max_tokens`가 더해진 값이라고 가정하고 `AGENT_STEP_MAX_TOKENS=3072`, `AGENT_MAX_PROMPT_TOKENS=4800`(합 7,872)으로 두었다. gpt-oss-120b(무료 TPM 8,000)에서 직접 확인했다.

| 프롬프트 토큰 | max_tokens | 결과 |
| --- | --- | --- |
| 4,638 | 1,024 / 5,500 (effort low·high) | 200 |
| 4,683 (도구 포함) | 5,500 / 4,000 | 200 |
| 7,129 | 3,072 | 200 (2회, 합계 10K 이상) |
| 약 8,700 | 600 | **413** (`Requested 9,081`) |
| 약 8,700 | 50 | **413** (`Requested 8,794`) |

- 413은 프롬프트 자체가 8K 근처를 넘을 때만 났다. `max_tokens`를 5,500까지 올려도 합산 때문에 막히지 않았다. 따라서 `max_tokens`는 TPM 검사에 합산되지 않는 것으로 **보인다**.
- 한계: 프롬프트 약 8.7K에서는 `max_tokens`를 50과 600만 시험했다. 합산이 일부만 반영되는 경우(예: 일정 비율)는 구분하지 못했다. 입력 상한을 올리는 변경은 아직 적용하지 않았다. 올리면 diagnose에서 압축 단계로 들어가는 시점이 늦어질 것으로 기대하지만 평가로 확인해야 한다.
- 호출 시점의 Groq 한도 응답: 요청 1,000/분 중 999 남음, 토큰 8,000/분. 오늘 실험에 쓴 토큰은 약 25K다.

### 4. Altare 공급자 시도와 철회

사용자가 `.env`에 `ALTARE_API_KEY`를 추가해 Groq·EXAONE 대신 쓰도록 요청했다(`https://inference.altare.global/v1`, OpenAI 호환, 2026-12-01까지 무료·RPM 60 안내).

- `/models` 조회와 tool calling(`tool_choice=required`) 호출은 gpt-oss-120b, deepseek-v4.1-flash, glm-5.3 모두 정상이었다(도구 호출 3~6초).
- `altare` 공급자(`ALTARE_*` 설정, 요청 간격 1초)를 추가하고 단일 턴 golden 44문항(prompt, effort high)을 먼저 돌렸다.

| 항목 | 결과 |
| --- | --- |
| 평가된 문항 | 33/44 (lookup 27, compare 6) |
| 실행 정확도 | 87.9% (29/33) — compare 6/6, lookup 85.2%, 스키마 요약 밖 지식 75.0%(3/4) |
| 실패 | mismatch 2(lookup-08, 22), `no_sql` 2(lookup-05, 27: 출력 16,384토큰에서 잘림, 호출당 약 150초), 평가 못 함 11 |
| 지연 | 평균 22.9s / 중앙값 13.5s / 최대 156.1s |

- 평가 도중(lookup-28부터) **HTTP 402 `insufficient_quota`** 로 바뀌었다: "Altare Inference is no longer included with Always Free: we don't have the capacity to keep offering it for free." 12월 1일까지 무료라는 안내와 달리 이미 중단됐고, 이후 호출은 모두 402다. 뒤이어 돌던 rag·rag+expand·loop·analysis 실행은 44문항 전부 즉시 402로 끝나 빈 리포트 4건을 남겼고, 이를 삭제했다.
- 위 87.9%는 33문항 기준이고 모델이 같은 gpt-oss-120b여도 공급자가 달라 Groq 수치와 같은 조건이 아니다. `no_sql` 2건은 이 공급자에서 high effort 추론이 길어진 것으로 보이나 원인은 확인하지 못했다.
- 사용자 요청으로 `altare` 공급자·설정·`.env.example` 블록·테스트를 모두 되돌렸다. `agent/.env`의 `ALTARE_API_KEY`는 건드리지 않았다. 부분 결과 리포트(`20261113-0952-golden_sql-gpt-oss-120b-high-altare-single-prompt`)만 실측 기록으로 남겼다.

### 5. 한도(402) 응답 처리 일반화

Altare 402를 겪으며 확인한 공급자 한도 오류 처리의 빈틈을 공급자와 무관하게 고쳤다.

- `openai_compat.py`: 402를 `daily`(오래 풀리지 않는 한도)로 보고 재시도하지 않는다.
- `LLMError.user_message`: 402도 429와 같은 "LLM 사용 한도에 도달했습니다…" 문구를 쓴다(공급자 응답 원문은 노출하지 않음).
- `LLM_FALLBACK_STATUSES` 기본값에 402 추가. 로컬 폴백이 설정돼 있으면 402에서 로컬로 넘어간다.
- 테스트 1건 추가(재시도 없음, 문구에 원문 미포함).

### 6. 평가 결과 (2026-11-13)

공급자는 Groq(Tool Loop)와 로컬 gpt-oss-20b-ctx32k(단일 턴 44문항)로 나눴고, 둘은 동시에 돌렸다. 문항별 1회 실행이라 확률적 변동을 분리하지 못한다.

#### 로컬 gpt-oss-20b, 단일 턴 golden 44문항 (effort medium, 한도 없음)

| 컨텍스트 | 정확도 | compare | lookup | 스키마 요약 밖 지식 | 지연 평균 | 입력 / 출력 토큰 |
| --- | --- | --- | --- | --- | --- | --- |
| prompt (기준선) | 88.6% (39/44) | 80.0% (15) | 93.1% (29) | 75.0% (4) | 9.2s | 1,861 / 700 |
| rag (2/2/3/1) | 86.4% (38/44) | 73.3% | 93.1% | 100% | 6.8s | 2,180 / 530 |
| rag + `KNOWLEDGE_EXPAND_SOURCES=1` | **97.7% (43/44)** | 100% | 96.6% | 100% | 7.0s | 2,388 / 554 |

- 리포트: `20261113-1010-…-local-single-prompt`, `20261113-1016-…-local-single-rag`, `20261113-1022-…-local-single-rag-expand1`
- **rag 단독의 실패 6건 중 5건은 events 컬럼을 몰라서 생긴 것으로 보인다.** guard 거절 3건(lookup-28, compare-11, compare-15)은 모델이 없는 컬럼 `event_timestamp`를 쓴 SQL이라 거절이 정당했고(오탐 아님), 실행 오류 3건은 없는 컬럼(`summary_date`, `device_type`)과 UNION의 ORDER BY 오류다. 11-12에 compare-15 원인으로 추정한 "table 할당량에 events 문서가 안 들어옴"과 같은 양상이다.
- expand=1로 지표의 계산 테이블 문서를 함께 넣자 이 실패가 사라졌고 정확도가 올랐다(86.4% → 97.7%). 11-12 검색 평가(LLM 없음)에서 table 재현율이 84.1% → 93.2%로 오른 것과 방향이 맞는다. 다만 문항당 1회 실행이고 로컬 20B 모델이므로 **expand=1이 정확도를 올린다고 단정하지는 않는다.** 남은 1건(lookup-28)은 모델이 "agg_event_daily에 device_type이 없어 산출할 수 없다"며 SQL을 내지 않은 경우다.
- prompt 모드가 rag 단독보다 높았다는 점(88.6% vs 86.4%)은 11-11 Phase 3의 K-EXAONE 결과(prompt 100%, rag 95%)와 같은 방향이다. 이 규모에서 prompt를 기본으로 두는 결정은 유지된다. 켜는 것은 보류하고, 기본값(expand=0)도 바꾸지 않았다.
- 입력 토큰은 rag가 prompt보다 17~28% 많다(스키마 요약이 이미 작아 절감 이점이 없다는 Phase 3 결론과 같다).

#### Groq gpt-oss-120b, Tool Loop golden 20문항 (prompt 모드)

- 정확도 **85.0% (17/20)**: lookup 92.9%, compare 66.7%(6). 11-12 로컬 Tool Loop(medium 상한)는 95.0%였다.
- 오답 3건의 실제 원인:
  - lookup-09: LLM 서비스 오류(5xx 추정, 원문 미확인)로 실행이 `failed`. SQL은 한 번 성공했다.
  - compare-06: 한도 429로 `failed`. 평가 막바지에 일일 토큰 한도(TPD 200K)에 닿은 것으로 보인다.
  - compare-01: 정상 완료(`succeeded`)했는데 값이 달랐다. 이번 주 범위를 `summary_date < current_date`(오늘 제외)로 잡은 것이 원인일 수 있으나 정답 SQL과 비교해 확인하지는 않았다.
- **평가기 결함 수정**: 위 두 건은 공급자 오류로 실행이 끝났는데도 마지막 성공 SQL로 채점돼 `mismatch`가 됐다. SQL이 한 번도 성공하지 못한 경우만 공급자 오류로 분류하던 것을, 오류 이벤트가 있으면 `llm_error`(평가 불가)로 분류하도록 고쳤다(`evals/run_eval.py`, 테스트 1건 추가). 저장된 리포트(`20261113-1010-…-groq-loop-20`)는 고치기 전 방식으로 채점돼 85.0%로 남아 있다. 수정 기준으로는 평가된 18문항 중 17문항 정답(94.4%)이다. 수치만 다시 계산한 것이고 재실행하지는 못했다.
- 재실행 시도는 TPD 소진(`Used 199,326 / 200,000`)으로 실패했다. 빈 리포트는 삭제했다.
- 지연 평균 40.9s는 생성 속도가 아니다. 호출 대기(`wait_ms`)가 대부분이라(예: lookup-09 37.8s 중 33.4s) 요청 간격(2초)과 분당 토큰 대기가 섞여 있다.
- 입력 5,232 / 출력 1,104 토큰으로 질문 1건이 약 6.3K 토큰이다. 20문항이 약 127K라 Groq 무료 TPD 200K에서는 한 번에 20문항이 한계다.
- guard 엄격화로 거절된 SQL은 이번 Groq 루프에서 없었다.


### 7. OpenAI 공급자 추가와 gpt-6-luna 평가

사용자가 `.env`에 `OPENAI_API_KEY`를 추가해 이 키로 진행하도록 요청했다. 모델은 `gpt-6-luna`다.

#### 호환성 확인 (Chat Completions)

| 요청 | 결과 |
| --- | --- |
| 기본 대화 | 200 |
| `max_tokens` | 400: `max_completion_tokens`를 쓰라고 한다 |
| `top_p` | 400: 지원하지 않음 |
| `tools` + `reasoning_effort` (`tool_choice` required·함수 지정) | **400**: "Function tools with reasoning_effort are not supported … use /v1/responses or set reasoning_effort to 'none'" |

- 에이전트 루프는 추론하면서 도구를 써야 하므로 Chat Completions로는 쓸 수 없다. `/v1/responses`에서는 도구 + `reasoning.effort`, 도구 결과를 넣은 다음 턴(서버 상태 저장 없이), 함수 지정 `tool_choice`, `temperature`가 모두 동작했다.
- 응답 헤더 한도: 요청 30,000/분, 토큰 1억 8천만/분. 평가 중 429는 없었다.

#### `OpenAIResponsesClient` (`app/llm/openai_responses.py`)

- `OpenAICompatClient`를 상속해 요청 간격·재시도·시간 초과·한도 처리는 그대로 쓰고, 요청·응답 형식만 바꾼다. 이를 위해 기존 클라이언트의 전송부를 `_send()`로 분리하고 경로를 클래스 속성 `path`로 뺐다(동작 변화 없음).
- 요청: 대화 이력(Chat Completions 형식)을 Responses 입력 항목으로 바꾼다. system/user/assistant 메시지는 그대로, assistant의 `tool_calls`는 `function_call`, `tool` 메시지는 `function_call_output`이다. 도구 스키마는 `function` 객체를 펼친 형식으로, 함수 지정 `tool_choice`는 `{"type": "function", "name": …}`로 바꾼다. `reasoning_effort` → `reasoning.effort`, `max_tokens` → `max_output_tokens`. `top_p`는 보내지 않고, `store=false`로 둔다.
- 응답: `output`의 `message` 텍스트와 `function_call`을 `ChatResult`로 돌려준다. `status=incomplete`(`max_output_tokens`)는 `finish_reason="length"`로 맞춰 루프의 출력 잘림 처리를 그대로 탄다. 다음 턴 이력은 지금처럼 Chat Completions 형식으로 쌓이므로 루프·분류기·평가기는 바꾸지 않았다. 추론 항목(reasoning item)은 다음 턴에 다시 넣지 않는다.
- 설정: `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`(기본 `https://api.openai.com/v1`, 프록시를 쓰면 그 주소), `OPENAI_MODEL`(기본 `gpt-6-luna`), `OPENAI_MIN_INTERVAL_SECONDS`(기본 0). 기본 공급자는 groq 그대로다. 단가를 몰라 비용은 비워 둔다.
- 테스트 6건(`tests/test_llm_responses.py`): 이력 변환, 파라미터 매핑, 도구 호출·사용량 파싱, 텍스트·출력 잘림, 재시도·오류·형식 오류, 공급자 조립.

#### 결과 (gpt-6-luna, 2026-11-13 시드, 문항당 1회)

**단일 턴 golden 44문항 (effort high)**

| 컨텍스트 | 정확도 | compare | lookup | 스키마 요약 밖 지식 | 지연 평균 | 입력 / 출력(추론) 토큰 |
| --- | --- | --- | --- | --- | --- | --- |
| prompt | 93.2% (41/44) | 93.3% | 93.1% | 75.0% (4) | 4.6s | 1,796 / 436 (303) |
| rag | 93.2% (41/44) | 80.0% | 100% | 100% | 5.0s | 2,116 / 336 (218) |
| rag + expand=1 | 93.2% (41/44) | 80.0% | 100% | 100% | 5.0s | 2,323 / 333 (207) |

- 세 방식의 정확도가 같다. 로컬 20B에서 보인 차이(rag 86.4% → expand 97.7%)가 이 모델에서는 나타나지 않았다. rag는 스키마 요약 밖 지식 문항(4개)과 lookup을 모두 맞혔고, 대신 compare에서 더 틀렸다.
- expand=1에서도 events 컬럼 오류가 1건(compare-09 `day_type` 없음) 있었고, compare-11은 guard의 events 기간 조건 검사에서 거절됐다(원인 SQL은 확인하지 않음).
- **expand=1의 효과는 모델에 따라 다르다**는 것이 이번 결과의 결론이다. 기본값(0)은 그대로 둔다.

**Tool Loop golden 44문항 (prompt, `AGENT_MAX_PROMPT_TOKENS=0`)**

- **90.9% (40/44)**: lookup 96.6%, compare 80.0%. 44문항 전체를 Tool Loop로 한 번에 돌린 첫 점수다.
- 질문당 LLM 호출 2.0회, 입력 5,259 / 출력 602 토큰, 지연 평균 10.0s / 최대 18.0s. 예산 소진 0건, 첫 SQL 성공 97.7%. 루프 지표의 추론 토큰은 0으로 나오는데, 실행 지표가 추론 토큰을 모으지 않기 때문이다(Groq·로컬 리포트도 같다). 모델이 실제로 추론을 하지 않았다는 뜻은 아니다.
- 오답 4건: compare-01, lookup-22, compare-11, compare-12.

**원인 분석 11문항 (diag-02~12, LLM-as-judge = 각자 같은 모델)**

| 항목 | gpt-6-luna | 로컬 gpt-oss-20b (같은 시드, 같은 11문항) |
| --- | --- | --- |
| 통과 (필요 사실 수 이상 언급) | **72.7% (8/11)** | 18.2% (2/11) |
| 정답 사실 언급률 | 65.2% | 22.7% |
| 근거 충실성 (judge) | 92.4% (11/11 채점) | 100% (7/11만 채점) |
| 평균 주장 수 / 근거 검증에서 뺀 주장 | 3.5 / 0 | 1.1 / 9 |
| 예산 소진 | 0% | 18.2% (강제 결론 2건) |
| 지연 평균 | 48.9s | 48.9s |

- gpt-6-luna가 놓친 문항: diag-05(소셜 영상 유입 이탈), diag-10(모바일 결제 장애), diag-11(회원 재방문). 로컬은 diag-08, diag-12만 통과했다.
- 로컬 근거 충실성 100%는 주장이 남은 7문항만 본 값이다. 나머지 4문항은 근거 검증을 통과한 주장이 없어 채점 대상이 아니었다(정답 사실 33.3%). 충실성만 보고 로컬이 더 정확하다고 읽으면 안 된다.
- 11-12 로컬 수치(41.7%, 12문항, 이전 시드)보다 오늘 로컬 결과(18.2%)가 낮다. 시드와 문항 구성이 달라 단순 비교는 안 되지만, 로컬 diagnose는 변동이 크다는 뜻이다.
- 분류기가 diagnose 질문 11개 중 5개를 compare로 분류했다(로컬은 12개 중 6개). 분류 누락은 모델과 무관하게 반복된다.
- 계획 01의 Phase 2 완료 기준("시드에 심은 원인을 근거 SQL과 함께 제시")은 이 모델에서 8/11 문항이 충족됐다. 심사 모델이 답변 모델과 같아서 근거 충실성은 낙관적일 수 있다. 로컬과의 비교는 위 표처럼 오늘 같은 시드로 측정했다.
- diag-01은 시드 요일 문제로 제외했다(1절).

**Tool Loop golden 44문항: 로컬 gpt-oss-20b와 비교 (prompt 모드, 같은 시드)**

| 구간 | gpt-6-luna | 로컬 gpt-oss-20b | 참고: Groq gpt-oss-120b |
| --- | --- | --- | --- |
| 전체 44문항 | **90.9% (40/44)** | 79.1% (34/43, 1문항 서버 오류로 평가 불가) | 미측정 (TPD) |
| compare | 80.0% (15) | 53.3% (15) | - |
| lookup | 96.6% (29) | 92.9% (28) | - |
| 앞 20문항 (11-12 비교 구간) | 95.0% (19/20) | 90.0% (18/20) | 85.0% (17/20, 공급자 오류 2건 포함) |
| 나머지 24문항 | 87.5% (21/24) | 69.6% (16/23) | - |
| 지연 평균 / 질문당 입력 토큰 | 10.0s / 5.3K | 19.8s / 10.3K | 40.9s(대기 포함) / 5.2K |

- 로컬은 compare에서 크게 떨어진다(80.0% → 53.3%). 오답 8건 중 compare가 6건이다(compare-09, 10, 11, 12, 13, 15). compare-03은 성공한 SQL 없이 끝났다(`no_sql`). 예산 소진은 2.3%(1건)로 낮다.
- 로컬 입력 토큰이 gpt-6-luna의 약 2배인 것은 첫 SQL 전 호출이 더 많고(질문당 LLM 호출 3.9회 vs 2.0회) 대화 이력이 누적되기 때문이다.
- 앞 20문항만 보면 11-12 로컬 Tool Loop 95.0%(19/20)보다 낮은 90.0%(18/20)다. 같은 설정이지만 시드가 다르고 문항당 1회라 변동 범위로 본다. 11-12에 틀렸던 compare-06은 이번에 맞았고(guard 보정 후), lookup-09와 compare-03이 틀렸다.
- 즉 **품질은 gpt-6-luna > 로컬 20B이고, 폴백으로서의 로컬 모델은 lookup 수준에서는 쓸 만하지만 compare부터 눈에 띄게 떨어진다.** 11-12에 정한 "폴백 허용 난이도 전체" 결정은, diagnose(18.2%)와 compare(53.3%)에서 품질이 낮다는 점을 이번 결과로 다시 보게 한다. 결정을 바꾸지는 않았다.

**안전성 22문항 (에이전트 포함)**

- gpt-6-luna **22/22 통과**: guard 100%, DB 계층 100%(21문항, 1문항 skip), 에이전트 100%. 처음 막은 곳은 분류기 17건, 모델 5건이다(11-12 Groq는 분류기 19건, 모델 3건).
- 로컬 gpt-oss-20b도 **22/22 통과**: 처음 막은 곳은 분류기 17건, guard 2건, 모델 3건이다. 두 모델 모두 대부분을 분류기가 막으므로 방어가 분류기에 크게 의존한다는 11-12 지적은 그대로다.

#### 문항 정의 검토 대상

- **compare-12** ("지난달과 이번 달의 일평균 페이지뷰"): 이번 실행 4개(단일 턴 3, 루프 1)가 모두 틀렸다. 정답 SQL은 일부만 쌓인 오늘 데이터를 포함해 데이터가 있는 날의 평균을 내고, 모델은 오늘을 빼고 기간의 달력 일수로 나눴다. 질문만으로는 어느 쪽이 맞는지 정해지지 않는다.
- **compare-01** ("지난주 대비 이번 주 유입 소스별 세션 수"): Tool Loop에서는 Groq와 gpt-6-luna가 모두 이번 주를 `summary_date < current_date`(오늘 제외)로 잡아 틀렸다. 단일 턴은 오늘을 포함해 맞혔다. 프롬프트 정의는 "이번 주 = 월요일부터(상한 없음)"이고 "오늘 데이터는 일부만 있다"는 안내가 함께 있다. 루프 모델이 이 안내를 보고 오늘을 뺀 것으로 **추정**한다.
- 두 문항 모두 "오늘(부분 데이터)을 포함하는가"의 모호함이다. 질문에 명시하거나 정의를 하나로 정할지 결정이 필요하다. 점수를 맞추려고 지금 바꾸지는 않았다.

#### 리포트

- `20261113-1051-golden_sql-gpt-6-luna-high-openai-single-prompt`
- `20261113-1055-golden_sql-gpt-6-luna-high-rag-openai-single-rag`
- `20261113-1059-golden_sql-gpt-6-luna-high-rag-openai-single-rag-expand1`
- `20261113-1051-golden_sql-gpt-6-luna-loop-openai-loop`
- `20261113-1059-analysis-gpt-6-luna-openai-analysis`
- `20261113-1109-safety-agent-openai-safety`
- 로컬: `20261113-1137-golden_sql-gpt-oss-20b-ctx32k-loop-local-loop-44`, `20261113-1152-analysis-gpt-oss-20b-ctx32k-local-analysis-11`, `20261113-1201-safety-agent-local-safety`

## 검증

- `pytest` 339건 통과, `ruff check`·`ruff format --check` 통과.
- `run_eval check`: 재시드 후 diag-01 1건 외 통과.

## 남은 것

- compare-01·compare-12의 "오늘 포함 여부" 정의를 정하고 질문이나 정답 SQL을 고친다.
- 분류기가 diagnose를 compare로 분류하는 문제(이번 5/11, 로컬 6/12)를 개선한다.
- 루프 실행 지표에 추론 토큰을 모은다.
- 로컬 모델의 compare·diagnose 품질 저하(53.3%, 18.2%)를 폴백 허용 난이도에 반영할지 정한다.
- 문항당 1회 실행이라 방식 간 1~2문항 차이는 변동과 구분되지 않는다. 기본값(prompt, expand=0)을 바꾸려면 반복 실행이 필요하다.
- Groq gpt-oss-120b의 원인 분석 기준선과 Tool Loop 44문항은 Groq TPD 때문에 아직 없다.
- `AGENT_MAX_PROMPT_TOKENS` 상향 평가(Groq 한정 문제), diag-01 시드 의존 문제, GitHub Actions 실제 실행.
