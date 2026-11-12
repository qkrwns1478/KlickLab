# 로컬 LLM 폴백 도입 계획

- 작성일: 2026-11-12
- 상위 계획: [01-text_to_sql_LLM_분석_에이전트_구현_계획](01-text_to_sql_LLM_분석_에이전트_구현_계획.md)

## 1. 배경과 목표

에이전트의 LLM은 원래 Claude API였으나 비용 문제로 무료 API(Groq `openai/gpt-oss-120b`, K-EXAONE)를 쓰고 있다. 이 때문에 두 가지 제약이 있다.

- 한도 제한: Groq 무료 등급의 TPM·TPD 초과(429), 요청 크기 초과(413). 평가를 연속으로 돌리거나 사용 중 한도가 소진되면 작업이 멈춘다.
- 응답 지연: K-EXAONE는 골든 평가에서 평균 약 158초에 공급자 오류가 11건 중 6건이었고, Groq도 중앙값 8~18초, 최대 41초였다.

**목표**: 기본은 외부 API를 쓰고, 한도 초과로 호출이 실패하면 같은 요청을 로컬 모델에 다시 보내 에이전트가 멈추지 않게 한다.

- 범위: 개발·테스트와 사용 중 한도 소진 대응. 현재 실제 배포 계획은 없다.
- 범위 밖: 로컬 모델 파인튜닝, 여러 GPU 서빙, 외부 API 간 비용 최적화 라우팅.

## 2. 현재 구조와 적용 지점

LLM 호출은 모두 `LLMClient` 프로토콜(`agent/app/llm/base.py`)을 거친다. 호출처는 `loop.py`, `router.py`, `text_to_sql.py`이고, 클라이언트는 `build_llm_client`(`app/llm/__init__.py`)가 `ask.py`, `runs.py`에서 만든다.

| 현재 동작 | 폴백 설계에 미치는 영향 |
| --- | --- |
| `OpenAICompatClient`가 429/5xx를 `retry-after`(최대 60초)만큼 기다리며 최대 3회 재시도한다. 하루 한도(`per day`)만 즉시 실패한다. | 폴백이 있으면 분당 한도에서 최대 3분 넘게 기다린 뒤에야 폴백된다. 폴백이 있을 때는 재시도 대기를 짧게 제한해야 한다. |
| 429 대기 시간은 `wait_ms`로 시간 예산에서 제외된다. | 로컬 모델의 생성 시간은 제외되지 않아 `diagnose`(180초) 예산이 빠듯할 수 있다. |
| 대화 이력은 OpenAI Chat Completions 형식(`assistant_message()`)이다. | 로컬 서버도 같은 형식이므로 **실행 도중 모델이 바뀌어도 이력을 그대로 넘길 수 있다.** |
| `agent_max_prompt_tokens=4800`은 Groq 무료 등급 TPM 8K 때문에 정한 값이다. | 로컬에는 불필요한 제약이다. 폴백 시에도 같은 값을 쓰면 안전하지만 불필요하게 이력이 압축된다. |
| `reasoning_effort`, `temperature=1.0`, `top_p=0.95`는 gpt-oss 기준이다. | 모델 계열이 다르면 파라미터를 무시하거나 거부할 수 있다. 공급자별 파라미터 처리가 필요하다. |

## 3. 설계

### 3.1 구성

```
build_llm_client(settings)
 └─ FallbackLLMClient(primary=OpenAICompatClient(groq|exaone), fallback=OpenAICompatClient(local))
      ├─ chat(): primary 호출 → 폴백 대상 오류면 fallback 호출
      ├─ cooldown: primary 한도 초과 후 일정 시간 primary 건너뜀 (프로세스 공유)
      └─ aclose(): 둘 다 닫음
```

- `FallbackLLMClient`는 `LLMClient` 프로토콜을 구현한 래퍼다. 루프, 라우터, 평가 코드는 수정하지 않는다.
- 로컬 모델은 **FastAPI 프로세스 밖의 추론 서버**(Ollama 또는 llama.cpp server)로 띄우고, 같은 `OpenAICompatClient`로 호출한다. 클라이언트에 `local` provider 분기만 추가한다.
- 체인은 `[primary, fallback]` 두 단계로 시작하되, 구현은 목록을 순서대로 시도하는 형태로 두어 이후 "API → 다른 API" 같은 구성도 같은 코드로 처리한다.

### 3.2 폴백 조건

| 오류 | 폴백 | 이유 |
| --- | --- | --- |
| 429 (분당·일일 한도) | 한다 | 핵심 사용 사례 |
| 413 (요청이 한도보다 큼) | 한다 | Groq 무료 등급 TPM 초과 |
| 5xx, 연결 실패 (재시도 소진 후) | 한다 | 공급자 장애 |
| 408 (응답 시간 초과) | 기본 끔 | 로컬이 더 느릴 수 있어 같은 시간 예산 안에 끝난다는 보장이 없다. 설정으로 켠다. |
| 401/403 (인증) | 하지 않는다 | 설정 오류이므로 숨기지 않고 그대로 드러낸다. |
| 400 등 요청 오류 | 하지 않는다 | 로컬에 보내도 같은 오류다. |

`LLM_FALLBACK_STATUSES` 설정으로 조정할 수 있게 한다.

### 3.3 기다리지 않고 넘기기

`min_interval`과 재시도 대기는 폴백이 있을 때 의미가 달라진다.

- primary에는 `max_retries`와 `retry-after` 대기 상한을 폴백 설정 시 낮춘다. 예: 대기 상한 5초, 재시도 1회. 한도가 곧 풀리는 경우만 기다리고, 그 이상이면 바로 폴백한다.
- `retry-after`가 상한보다 길면 대기하지 않고 즉시 실패시켜 폴백한다.

### 3.4 쿨다운과 실행 내 고정

- **쿨다운**: primary가 한도 초과로 실패하면 `retry-after`(없으면 기본 60초, 하루 한도면 길게) 동안 primary를 건너뛰고 바로 폴백한다. 한 실행에 LLM 호출이 최대 15회라서, 호출마다 primary의 429를 다시 맞는 낭비를 막는다. 쿨다운 상태는 프로세스 단위로 공유한다(다중 워커면 워커별).
- **실행 내 고정**: 한 실행(run) 도중 폴백이 일어나면 그 실행은 끝까지 폴백 모델로 진행한다. 호출마다 모델이 왔다 갔다 하면 추론 스타일이 섞이고 품질을 설명하기 어렵다. 다음 실행부터는 쿨다운이 끝났으면 다시 primary를 쓴다.
  - 구현: 클라이언트는 상태 없이 두고, 루프가 실행 시작 시 `LLMClient` 세션 객체(`client.session()`)를 받아 고정 여부를 그 안에 둔다. 1차 구현부터 적용한다.

### 3.5 공급자별 파라미터

- `OpenAICompatClient`에 `drop_params`(전송하지 않을 파라미터)와 `param_map`(이름 변환)을 추가한다.
- 로컬 공급자 기본값: `temperature`·`top_p`는 모델 권장값으로 별도 설정, `reasoning_effort`는 gpt-oss 계열일 때만 전달한다. 서버가 `reasoning_effort`를 최상위로 받는지 `chat_template_kwargs`로 받는지는 3.8의 검증 단계에서 확인한다.
- 로컬은 TPM 제약이 없으므로 폴백 시 입력 토큰 상한을 높일 수 있게 `ChatResult`가 아니라 **클라이언트 속성**(`max_prompt_tokens`)으로 노출한다. 루프는 이 값이 있으면 `agent_max_prompt_tokens` 대신 쓴다. 1차 구현에서는 기존 값을 그대로 쓰고, 품질 비교 후 완화 여부를 정한다.

### 3.6 시간 예산

- 로컬 추론 시간은 대기가 아니라 실제 작업 시간이므로 예산에서 제외하지 않는다. 대신 폴백 모델로 진행하는 실행에는 시간 한도에 배율(`LLM_FALLBACK_TIME_FACTOR`, 기본 2.0)을 적용하는 방안을 검토한다. 실측 후 확정한다.
- `diagnose`는 로컬에서 15회 호출을 모두 쓰면 시간 한도를 넘길 가능성이 높다. 이 경우 기존 예산 소진 경로(부분 결과 + 안내)가 동작하는지 확인한다.

### 3.7 동시성과 장애 처리

- 로컬 GPU는 동시에 1~2건만 처리하므로 폴백 클라이언트 앞에 `asyncio.Semaphore`(기본 1)를 둔다. 대기열이 길어지면 호출 시간 제한이 먼저 걸린다.
- 로컬 서버가 꺼져 있으면 연결 오류가 난다. 이때는 **primary의 원래 오류(429)를 사용자 문구로 돌려준다.** 연결 오류를 보여 주면 원인을 오해하게 된다.
- 시작 시 로컬 서버 헬스 체크(`/v1/models`)를 한 번 하고, 실패해도 서버는 뜨게 하되 경고 로그를 남기고 폴백을 비활성 상태로 둔다. 쿨다운 중 주기적으로 재확인한다.

### 3.8 관측성과 평가의 정합성

- `ChatResult`에 `provider`, `model`을 추가하고, 실행 기록에 호출별 모델과 `fallback` 여부를 남긴다. 실행 요약에 `fallbackCalls`, `primaryError`를 추가한다. DB 저장이 필요하면 Flyway 마이그레이션으로 처리한다(기존 `agent_runs` 구조 확인 필요).
- 사용자에게는 폴백으로 응답했음을 표시만 한다(재시도 선택지는 두지 않는다). 프론트엔드 응답 화면에 작은 표시 하나만 둔다. 레이아웃으로 구분하고 설명 문구는 늘리지 않는다.
- **평가 실행은 폴백을 기본으로 끈다** (`--no-fallback` 또는 평가 러너가 `LLM_FALLBACK_PROVIDER=none`을 강제). 폴백이 섞이면 보고서의 모델별 정확도를 해석할 수 없다. 로컬 모델 자체의 평가는 `LLM_PROVIDER=local`로 단독 실행한다.
- 보고서 헤더에 모델이 섞였을 때 경고를 남긴다.

### 3.9 설정

```
LLM_PROVIDER=groq                # 기존: groq | exaone | local
LLM_FALLBACK_PROVIDER=none       # none | local
LLM_FALLBACK_STATUSES=429,413,500,502,503,504
LLM_PRIMARY_MAX_WAIT_SECONDS=5   # 폴백이 있을 때 primary의 retry-after 대기 상한
LLM_FALLBACK_COOLDOWN_SECONDS=60
LOCAL_BASE_URL=http://localhost:11434/v1
LOCAL_MODEL=gpt-oss:20b
LOCAL_API_KEY=local
LOCAL_NUM_CTX=16384              # 서버 쪽 설정과 일치시킨다 (Ollama는 초과 시 앞부분을 조용히 자른다)
LOCAL_TEMPERATURE / LOCAL_TOP_P  # 모델 권장값
LOCAL_MAX_CONCURRENCY=1
```

기본값은 폴백 없음이라 기존 동작은 바뀌지 않는다.

## 4. 로컬 모델 선택

> 개발 PC 사양: RTX 5060 Ti 16GB, RAM 64GB, Core Ultra 9 285

| 후보 | 판단 |
| --- | --- |
| gpt-oss-20b (MXFP4, 약 13GB) | 1순위. 현재 Groq 모델(gpt-oss-120b)과 같은 계열이라 프롬프트, 추론 강도, tool 형식이 가장 잘 옮겨진다. |
| Gemma 4 26b (A4B MoE) | gpt-oss-20b 평가 후 결정. 공식 도구 사용 점수(τ²-bench)가 높지만 16GB에서 빠듯하다. `reasoning_effort` 대응이 필요하다. |
| Gemma 4 12b | 메모리 여유는 있으나 도구 사용 점수가 낮다는 비공식 수치가 있다. 대안·분류용 후보. |
| Gemma 4 e4b / e2b / 31b | 제외. e4b·e2b는 도구 사용 점수가 낮고, 31b는 4비트에서도 16GB를 넘는다. Ollama 기본 태그(`gemma4`)는 e4b이므로 받을 때 태그를 명시해야 한다. |
| Qwen3 14B / 30B-A3B (Q4) | 대안. tool calling 성능이 좋지만 파라미터 조정이 필요하다. |
| EXAONE 7.8B급 | 한국어에 유리하나 tool loop 신뢰성 검증이 필요하고, 라이선스가 비상업용이다. |
| gpt-oss-120b (RAM 오프로드) | 다른 서비스와 함께 돌리기에 부담이고 느려서 제외. |

추론 서버는 Windows에서 vLLM을 쓸 수 없으므로 Ollama 또는 llama.cpp server를 쓴다. RTX 50 시리즈는 CUDA 12.8 이상 빌드가 필요하다. 모델 목록과 속도는 제 지식 기준 추정이므로 Phase 0에서 실측한다.

## 5. 위험과 대응

| 위험 | 대응 |
| --- | --- |
| 로컬 모델의 SQL 정확도·tool loop 안정성이 낮다 | Phase 4에서 같은 평가셋으로 비교한다. 기준 미달이면 폴백 대상을 `lookup`·`compare` 난이도로 제한하거나, `diagnose`는 폴백 대신 한도 안내를 한다. |
| `tool_choice` 강제(`"required"`, 함수 지정)를 서버가 무시한다 | Phase 0에서 확인한다. 무시하면 llama.cpp server로 바꾸거나, 루프에서 tool 호출이 없을 때 재요청하는 보정을 로컬 한정으로 둔다. |
| Ollama가 컨텍스트 초과분을 조용히 자른다 | `num_ctx`를 명시하고, 로컬 클라이언트가 `usage.prompt_tokens`와 요청 추정치를 비교해 잘림이 의심되면 경고를 남긴다. |
| 폴백 중 실행이 느려 시간 예산 소진 | 3.6의 배율, 실측 후 조정. |
| 폴백 기록이 평가를 오염시킨다 | 3.8처럼 평가는 폴백을 끈다. |
| 사용자가 품질 저하를 모르고 쓴다 | 응답에 폴백 표시, 실행 기록에 모델 명시. |
| 쿨다운 상태가 다중 워커에서 공유되지 않는다 | 현재 단일 워커 전제. 워커를 늘리면 워커별로 한 번씩 429를 맞는 수준이라 허용한다. |

## 6. 배포 관점

현재 배포 계획이 없으므로 **개발 환경 전용 기능으로 정의**하고, 배포 때 정책만 정한다.

- `LLM_FALLBACK_PROVIDER=none`이 기본이라 배포 환경에 영향이 없다.
- 로컬 폴백을 배포에 가져가려면 GPU 서버(예: 24GB급)가 상시 필요하다. 트래픽이 적은 서비스라면 유료 API가 더 싸므로 권하지 않는다.
- 대신 `FallbackLLMClient`가 목록 기반이므로 배포 시에는 `[Groq 유료 → 다른 API]`처럼 API끼리 체인을 구성할 수 있다. 이 계획의 구현은 그 경우에도 재사용된다.
- GitHub Actions에는 GPU가 없으므로 CI는 지금처럼 API 키가 있을 때만 LLM 평가를 하고, 폴백은 끈다. 폴백 로직은 가짜 클라이언트로 단위 테스트한다.
- 시작 시 로컬 서버가 없을 때 서버가 정상 기동해야 하므로 도커 이미지나 `docker-compose`에 로컬 모델 의존을 넣지 않는다.

## 7. 구현 단계

### Phase 0. 로컬 서버 검증 (코드 변경 없음)

- Ollama 또는 llama.cpp server에 gpt-oss-20b를 올리고 `num_ctx` 16K 이상으로 설정한다.
- 확인 항목: `tools` 호출 형식, `tool_choice` 의 `"required"`와 함수 지정 동작, `reasoning_effort` 전달 방식, 입력 약 3K·출력 약 1K 토큰 요청의 지연, 한국어 SQL 설명 품질.
- 산출물: 결과 메모와 서버 선택(Ollama / llama.cpp).

**결과 (2026-11-12, Ollama 0.40.16, `gpt-oss:20b` MXFP4, RTX 5060 Ti 16GB)** — 작업 로그: [02-로컬_LLM_폴백_Phase0_검증](../logs/2026-11-12/02-로컬_LLM_폴백_Phase0_검증.md)

| 항목 | 결과 | 설계에 미치는 영향 |
| --- | --- | --- |
| 컨텍스트 | Ollama 기본 `num_ctx`가 4096이라 약 14.5K 토큰 입력의 앞부분이 **오류 없이 잘렸다.** 파생 모델(Modelfile `PARAMETER num_ctx 32768`)로 고정하면 정상이다. 32K에서도 100% GPU, VRAM 약 14.5GB. | 요청 단위로 `num_ctx`를 넘기는 방법(`options`)은 OpenAI 호환 엔드포인트에서 쓸 수 없으므로 **파생 모델 생성이 필수**다. 3.9의 `LOCAL_NUM_CTX`는 서버 쪽 설정이며, 시작 시 헬스 체크에서 `/api/show`의 `num_ctx`를 확인해 경고한다. |
| `tool_choice="required"` | 첫 단계 lookup 5건 모두 tool 호출, 인자 JSON 유효. | 문제 없음. |
| `tool_choice` 함수 지정 (`FORCE_FINAL`) | **무시됨.** 도구가 `final_answer` 하나뿐이어도 3회 중 1회 `run_sql`을 호출했다. | 루프가 `final_only`로 거절하고 재시도(`MAX_FORCED_CALLS=2`)하므로 즉시 깨지지는 않지만, 약 1/9 확률로 "결론 없음"이 될 수 있다. 로컬 한정으로 **강제 단계에서 잘못된 도구를 호출하면 올바른 도구만 쓰라는 메시지로 재요청**하는 보정을 Phase 2에 넣는다. |
| `reasoning_effort` | 최상위 파라미터로 반영된다(추론 길이 low 1.1K, medium 4.3K, high 11K자). `reasoning_tokens`는 항상 0으로 보고된다. | `drop_params`/`param_map` 없이 그대로 보내면 된다(gpt-oss 한정). 토큰 집계는 `completion_tokens`에 추론이 포함돼 있으므로 예산 계산에는 영향이 없다. |
| 속도 | 생성 약 80 tok/s. 단일 턴 SQL: low 6초, medium 16초, high 36초. 모델 로드 약 6초(콜드 스타트 첫 응답 65초는 디스크 읽기). | 3.6의 시간 배율이 필요하다(아래). |
| 한국어 답변 | 형식·문장 모두 자연스럽다. | |
| 서버 선택 | **Ollama로 진행한다.** llama.cpp 전환 사유(요청 단위 tool 강제 등)는 보정으로 해결 가능해 보류. | |

**골든 평가 (single, effort=high, prompt 모드, 20문항)** — Groq 120b와 같은 조건

| 모델 | 실행 정확도 | lookup / compare | 지연 평균 / 중앙값 / 최대 (ms) |
| --- | --- | --- | --- |
| Groq `gpt-oss-120b` (2026-11-11) | 95.0% (19/20) | 100% / 83.3% | 16,819 / 15,124 / 31,561 |
| 로컬 `gpt-oss-20b` (2026-11-12) | 95.0% (19/20) | 92.9% / 100% | 23,712 / 19,445 / 59,077 |

- 정확도는 같고 지연은 평균 약 1.4배다. 실패 1건(lookup-08)은 쓸 수 없는 집계 테이블을 골라 값이 달랐다.
- 이 평가는 단일 턴이다. **Tool loop(다단계) 품질은 아직 측정하지 않았다.** `golden --mode loop`와 `analysis`는 Phase 1 이후 `local` 공급자로 측정한다.
- 시간 예산: compare(60초) 최대 59초로 한도에 닿는다. 로컬 폴백 실행에는 3.6의 배율(2.0)이 필요하다.
- 측정에는 `local` 공급자가 없어 Groq 공급자의 base URL을 환경변수로 로컬 서버에 돌려 썼다(Phase 1에서 정식 공급자로 대체).

### Phase 1. `local` 공급자

- `Settings`에 `LOCAL_*` 추가, `build_llm_client`에 `local` 분기 추가.
- `OpenAICompatClient`에 `drop_params`/`param_map` 추가.
- `LLM_PROVIDER=local`로 단독 실행해 골든·분석 평가를 한 번 돌린다(Groq 결과와 비교).

### Phase 2. `FallbackLLMClient`

- 폴백 조건, primary 대기 상한, 쿨다운, 세마포어, 로컬 장애 시 primary 오류 반환을 구현한다.
- `ChatResult`에 `provider`, `model` 추가.
- 단위 테스트(가짜 클라이언트 + `httpx.MockTransport`):
  - 429/413/5xx에서 폴백, 401/400에서는 폴백하지 않음
  - `retry-after`가 상한보다 길면 대기 없이 폴백
  - 쿨다운 동안 primary 미호출, 쿨다운 후 복귀
  - 로컬 서버 다운 시 primary 오류 문구 반환
  - 폴백 응답의 tool_calls가 루프 이력에 정상 합쳐지는지 (`loop` 통합 테스트)

### Phase 3. 실행 기록·화면 연동

- 실행 요약과 로그에 모델·폴백 정보 추가. DB 마이그레이션은 1차에서 하지 않는다(9장).
- 응답 화면의 폴백 표시(스트림 이벤트 기반, 응답 직후에만).
- 평가 러너의 폴백 비활성화와 보고서 경고.
- 3.5의 `max_prompt_tokens`와 3.6의 시간 배율은 Phase 4 결과를 보고 반영한다.

### Phase 4. 품질·지연 평가

- 같은 평가셋(golden_sql, analysis_questions)을 Groq 단독, 로컬 단독으로 돌려 비교한다.
- 폴백 시나리오 점검: Groq 키 한도를 소진시키거나 모의 429를 주입해 중간 전환이 실제로 완주하는지 확인한다.
- 산출물: 로컬 모델 정확도와 지연 표, 폴백 허용 난이도 결정.

### Phase 5. 배포 정책 정리

- 배포 계획이 생기면 6장 기준으로 폴백 비활성 또는 API 체인으로 구성한다. 지금은 보류한다.

## 8. 완료 기준

- `LLM_FALLBACK_PROVIDER=none`이면 기존 테스트와 평가 결과가 달라지지 않는다.
- Groq에 모의 429를 주입했을 때 실행이 로컬 모델로 이어서 완료되고, 실행 기록에 폴백이 남는다.
- 로컬 서버가 꺼져 있어도 에이전트 서버가 기동하고, 한도 초과 시 기존과 같은 안내 문구가 나온다.
- 평가 보고서에서 모델이 섞이지 않는다.
- Phase 4에서 로컬 모델의 골든 실행 정확도가 Groq 대비 어느 정도인지 수치로 남고, 폴백을 허용할 난이도가 정해진다.

## 9. 열린 질문

- ~~폴백 응답을 사용자에게 어느 정도로 드러낼지~~ → 표시만 한다.
- ~~지난 대화를 다시 열었을 때도 폴백 표시가 보여야 하는지~~ → 필수가 아니다. 1차에서는 응답 직후 스트림 이벤트로만 표시하고 DB 마이그레이션은 하지 않는다. 필요해지면 `agent_runs`에 `model`, `fallback` 컬럼을 추가한다(후속).
- ~~실행 내 고정(3.4)을 1차에 넣을지~~ → 1차부터 적용한다.
