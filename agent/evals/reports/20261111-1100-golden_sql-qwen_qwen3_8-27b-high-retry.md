# golden SQL 평가 — qwen/qwen3.8-27b (reasoning_effort=high)

- 실행: 2026-11-11T11:00:34+09:00 / retry
- 실행 정확도: **83.3%** (5/6)
- 난이도별: compare 100.0% (3), lookup 66.7% (3)
- 상태: llm_error 1, match 5
- 생성 지연(ms): 평균 60543, 중앙값 60640, 최대 61702
- 평균 토큰: 입력 1524, 출력 638 (추론 516)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-04 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1 |
| lookup-07 | match | 61702 | 739 |  |
| lookup-12 | match | 59250 | 388 |  |
| compare-02 | match | 61030 | 663 |  |
| compare-03 | match | 60094 | 735 |  |
| compare-06 | match | 60640 | 1303 |  |

## 실패 문항

### lookup-04 — llm_error

질문: 지난주 페이지뷰가 가장 많은 페이지 5개는?

사유: LLM 응답 오류 429: {"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on output tokens per minute (OTPM): Limit 1

