# 로컬 LLM 폴백 Phase 0: Ollama + gpt-oss-20b 검증

## 요청

`docs/plans/02-로컬_LLM_폴백_도입_계획.md`의 Phase 0 진행. 코드는 변경하지 않고 로컬 추론 서버의 호환성과 품질을 실측했다.

## 작업 내용

### 1. 설치 마무리

- `gpt-oss:20b` 다운로드가 마지막 작은 파일에서 ollama.com 503으로 실패해 모델이 등록되지 않은 상태였다. `ollama pull`을 다시 실행해 등록했다.
- Ollama 기본 `num_ctx`가 4096이라(VRAM 기반 기본값) 파생 모델 `gpt-oss-20b-ctx16k`, `gpt-oss-20b-ctx32k`를 만들었다(`PARAMETER num_ctx`). 가중치는 공유하므로 디스크를 더 쓰지 않는다.

### 2. 호환성 점검

점검 스크립트는 실제 에이전트 프롬프트(`prompts.agent_messages`, `sql_messages`, `answer_messages`)와 tool 스키마(`run_sql`, `describe_table`, `final_answer`)를 `OpenAICompatClient`로 보냈다.

| 항목 | 결과 |
| --- | --- |
| 컨텍스트 잘림 | 기본(4096)에서는 약 14.5K 토큰 입력의 앞부분이 오류 없이 잘렸다. 16K·32K 파생 모델은 정상. 32K에서도 100% GPU, VRAM 약 14.5GB. |
| `tool_choice="required"` | lookup 5건 모두 tool 호출, 인자 JSON 유효 |
| `tool_choice` 함수 지정 | 무시됨 (도구가 `final_answer` 하나뿐인 경우 3회 중 1회 `run_sql` 호출) |
| `reasoning_effort` | 최상위 파라미터로 반영. `reasoning_tokens`는 항상 0 |
| 속도 | 생성 약 80 tok/s, 단일 턴 SQL low 6초 / medium 16초 / high 36초 |
| 한국어 답변 | 자연스러움 |

### 3. 골든 평가 (single, high, prompt 모드, 20문항)

- 로컬 `gpt-oss-20b-ctx32k`: 실행 정확도 95.0% (19/20), 지연 평균 23.7초 / 최대 59.1초
- 비교 기준 Groq `gpt-oss-120b`(2026-11-11): 95.0% (19/20), 지연 평균 16.8초 / 최대 31.6초
- 별도 `local` 공급자가 없어 Groq 공급자의 `GROQ_BASE_URL`, `GROQ_API_KEY` 환경변수를 로컬 서버로 돌려 실행했다.
- 보고서: `agent/evals/reports/20261112-1406-golden_sql-gpt-oss-20b-ctx32k-high-phase0-local.md`

## 결론과 후속

- 서버는 Ollama로 진행한다.
- Phase 2에 로컬 한정 보정을 추가한다: 결론 강제 단계에서 잘못된 도구를 호출하면 올바른 도구만 쓰라는 메시지로 재요청.
- 폴백 실행에 시간 한도 배율이 필요하다 (compare 최대 59초가 한도 60초에 닿음).
- Tool loop 품질은 미측정이다. Phase 1에서 `local` 공급자를 만든 뒤 `golden --mode loop`, `analysis`로 측정한다.
- 점검 스크립트는 임시 폴더에서만 썼고 저장소에는 넣지 않았다.
