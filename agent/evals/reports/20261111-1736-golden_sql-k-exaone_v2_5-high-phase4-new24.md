# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-11T17:36:47+09:00 / phase4-new24
- 모델: exaone / k-exaone_v2.5, 스키마 컨텍스트: prompt
- 실행 정확도: **92.3%** (12/13) — 공급자 오류로 평가 못 한 문항 11/24
- 난이도별: compare - (0), lookup 92.3% (13) / 스키마 요약 밖 지식 75.0% (4)
- 상태: llm_error 11, match 12, mismatch 1
- 지연(ms): 평균 23450, 중앙값 20844, 최대 58436
- 평균 토큰: 입력 915, 출력 294 (추론 255)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-15 | match | 8937 | 222 |  |
| lookup-16 | match | 42483 | 874 |  |
| lookup-17 | match | 23577 | 645 |  |
| lookup-18 | match | 12687 | 252 |  |
| lookup-19 | match | 12390 | 296 |  |
| lookup-20 | match | 24312 | 600 |  |
| lookup-21 | match | 20844 | 562 |  |
| lookup-22 | mismatch | 58436 | 1383 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 25953 | 522 |  |
| lookup-24 | match | 17875 | 427 |  |
| lookup-25 | match | 13390 | 313 |  |
| lookup-26 | match | 24655 | 617 |  |
| lookup-27 | match | 19311 | 351 |  |
| lookup-28 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| lookup-29 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-07 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-08 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-09 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-10 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-11 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-12 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-13 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-14 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |
| compare-15 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}} |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH last_week_visitors AS (
  SELECT client_id
  FROM agg_daily_users
  WHERE summary_date >= (date_trunc('week', current_date)::date - 7)
    AND summary_date < date_trunc('week', current_date)::date
),
prior_visitors AS (
  SELECT DISTINCT client_id
  FROM agg_daily_users
  WHERE summary_date < (date_trunc('week', current_date)::date - 7)
)
SELECT
  COUNT(DISTINCT CASE WHEN p.client_id IS NULL THEN l.client_id END) AS new_visitors,
  COUNT(DISTINCT CASE WHEN p.client_id IS NOT NULL THEN l.client_id END) AS returning_visitors
FROM last_week_visitors l
LEFT JOIN prior_visitors p ON p.client_id = l.client_id;
```

### lookup-28 — llm_error

질문: 15일 전 모바일 기기의 결제 완료 건수는?

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### lookup-29 — llm_error

질문: 최근 7일 일별 문의 접수 건수 추이는?

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-07 — llm_error

질문: 지난주 대비 이번 주 기기 유형별 세션 수를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-08 — llm_error

질문: 최근 7일과 그 전 7일의 nov_mega_sale 캠페인 세션 수를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-09 — llm_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-10 — llm_error

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-11 — llm_error

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-12 — llm_error

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-13 — llm_error

질문: 최근 7일과 그 전 7일의 유입 소스(traffic_source)별 전환 수를 비교해줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-14 — llm_error

질문: 최근 14일 일별 모바일과 데스크톱 세션 수를 날짜별 한 행에 나란히 보여줘

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

### compare-15 — llm_error

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: LLM 응답 오류 429: {"error":{"message":"day limit(100), called 100 times today","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}

