# golden SQL 평가 — qwen/qwen3.8-27b (reasoning_effort=high)

- 실행: 2026-11-11T10:52:03+09:00
- 실행 정확도: **70.0%** (14/20)
- 난이도별: compare 50.0% (6), lookup 78.6% (14)
- 상태: llm_error 6, match 14
- 생성 지연(ms): 평균 25493, 중앙값 16094, 최대 61483
- 평균 토큰: 입력 1276, 출력 644 (추론 571)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 11390 | 308 |  |
| lookup-02 | match | 17187 | 260 |  |
| lookup-03 | match | 15000 | 244 |  |
| lookup-04 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |
| lookup-05 | match | 797 | 245 |  |
| lookup-06 | match | 8000 | 746 |  |
| lookup-07 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit  |
| lookup-08 | match | 40296 | 881 |  |
| lookup-09 | match | 49344 | 434 |  |
| lookup-10 | match | 1110 | 415 |  |
| lookup-11 | match | 61483 | 813 |  |
| lookup-12 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |
| lookup-13 | match | 2891 | 660 |  |
| lookup-14 | match | 43328 | 2862 |  |
| compare-01 | match | 55483 | 2834 |  |
| compare-02 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |
| compare-03 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |
| compare-04 | match | 1906 | 757 |  |
| compare-05 | match | 48688 | 1412 |  |
| compare-06 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |

## 실패 문항

### lookup-04 — llm_error

질문: 지난주 페이지뷰가 가장 많은 페이지 5개는?

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

### lookup-07 — llm_error

질문: 최근 14일 기기 유형별 세션 수는?

사유: LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 

### lookup-12 — llm_error

질문: 최근 7일 nov_mega_sale 캠페인의 유입 소스·매체별 세션 수와 전환 수는?

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

### compare-02 — llm_error

질문: 지난주 세션 100개 이상인 유입 소스·매체 중 전환율(%)이 가장 높은 3개는?

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

### compare-03 — llm_error

질문: 최근 28일 동안 요일별(ISO 요일 번호, 월=1) 하루 평균 세션 수는?

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

### compare-06 — llm_error

질문: 지난주 대비 이번 주 이벤트 종류별 발생 건수 변화를 보여줘

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

