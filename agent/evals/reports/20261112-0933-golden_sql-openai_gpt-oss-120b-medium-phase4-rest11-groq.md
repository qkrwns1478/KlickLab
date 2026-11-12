# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-12T09:33:42+09:00 / phase4-rest11-groq
- 모델: groq / openai/gpt-oss-120b, 스키마 컨텍스트: prompt
- 실행 정확도: **60.0%** (6/10) — 공급자 오류로 평가 못 한 문항 1/11
- 난이도별: compare 50.0% (8), lookup 100.0% (2) / 스키마 요약 밖 지식 - (0)
- 상태: llm_error 1, match 6, mismatch 4
- 지연(ms): 평균 17287, 중앙값 7914, 최대 41500
- 평균 토큰: 입력 1694, 출력 467 (추론 358)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-28 | match | 1327 | 390 |  |
| lookup-29 | match | 1639 | 162 |  |
| compare-07 | mismatch | 3406 | 918 | 정답 3번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-08 | match | 9500 | 413 |  |
| compare-09 | mismatch | 29780 | 564 | 행 수 불일치 (정답 1, 예측 2) |
| compare-10 | match | 6327 | 546 |  |
| compare-11 | mismatch | 41500 | 361 | 행 수 불일치 (정답 3, 예측 6) |
| compare-12 | mismatch | 36781 | 690 | 행 수 불일치 (정답 1, 예측 2) |
| compare-13 | match | 39156 | 654 |  |
| compare-14 | match | 3452 | 441 |  |
| compare-15 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on tokens per minute (TPM): Limit 8000, |

## 실패 문항

### compare-07 — mismatch

질문: 지난주 대비 이번 주 기기 유형별 세션 수를 비교해줘

사유: 정답 3번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT
    device_type,
    SUM(CASE WHEN summary_date >= date_trunc('week', current_date)::date THEN sessions END) AS sessions_this_week,
    SUM(CASE WHEN summary_date >= (date_trunc('week', current_date)::date - 7)
             AND summary_date < date_trunc('week', current_date)::date THEN sessions END) AS sessions_last_week
FROM agg_user_session_hourly
WHERE summary_date >= (date_trunc('week', current_date)::date - 7)
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY device_type
ORDER BY device_type;
```

### compare-09 — mismatch

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
WITH daily_sessions AS (
    SELECT
        summary_date,
        SUM(sessions) AS daily_sessions
    FROM agg_user_session_daily
    WHERE summary_date >= current_date - 28
      AND summary_date < current_date
    GROUP BY summary_date
)
SELECT
    CASE
        WHEN EXTRACT(DOW FROM summary_date) IN (0, 6) THEN 'Weekend'
        ELSE 'Weekday'
    END AS day_type,
    AVG(daily_sessions)::numeric AS avg_sessions_per_day
FROM daily_sessions
GROUP BY day_type
ORDER BY day_type;
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 6)

```sql
SELECT
    date_trunc('day', timestamp)::date AS event_date,
    device_type,
    COUNT(*) AS payment_count
FROM events
WHERE event_name = 'is_payment'
  AND timestamp >= current_date - 15
  AND timestamp <  current_date - 13
GROUP BY event_date, device_type
ORDER BY event_date, device_type;
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
WITH monthly AS (
    SELECT 
        date_trunc('month', summary_date)::date AS month_start,
        SUM(page_views)                         AS total_page_views,
        COUNT(DISTINCT summary_date)            AS days
    FROM agg_page_daily
    WHERE summary_date >= (date_trunc('month', current_date) - interval '1 month')::date
      AND summary_date <  (date_trunc('month', current_date) + interval '1 month')::date
    GROUP BY month_start
)
SELECT
    CASE 
        WHEN month_start = date_trunc('month', current_date)::date THEN '이번 달'
        ELSE '지난달'
    END                                 AS month,
    (total_page_views::numeric / NULLIF(days, 0)) AS avg_daily_page_views
FROM monthly
WHERE month_start IN (
    date_trunc('month', current_date)::date,
    (date_trunc('month', current_date) - interval '1 month')::date
)
ORDER BY month_start;
```

### compare-15 — llm_error

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on tokens per minute (TPM): Limit 8000,

