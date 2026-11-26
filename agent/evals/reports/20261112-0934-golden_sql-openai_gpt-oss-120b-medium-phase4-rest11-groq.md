# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-12T09:34:01+09:00 / phase4-rest11-groq
- 모델: groq / openai/gpt-oss-120b, 스키마 컨텍스트: prompt
- 실행 정확도: **60.0%** (6/10) — 공급자 오류로 평가 못 한 문항 1/11
- 난이도별: compare 50.0% (8), lookup 100.0% (2) / 스키마 요약 밖 지식 - (0)
- 상태: llm_error 1, match 6, mismatch 4
- 지연(ms): 평균 19266, 중앙값 17827, 최대 41469
- 평균 토큰: 입력 1694, 출력 460 (추론 349)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-28 | match | 10561 | 430 |  |
| lookup-29 | match | 39297 | 197 |  |
| compare-07 | match | 3016 | 611 |  |
| compare-08 | mismatch | 5484 | 418 | 행 수 불일치 (정답 1, 예측 2) |
| compare-09 | mismatch | 32702 | 637 | 행 수 불일치 (정답 1, 예측 2) |
| compare-10 | llm_error | 0 | 0 | LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on tokens per minute (TPM): Limit 8000, |
| compare-11 | match | 3796 | 681 |  |
| compare-12 | mismatch | 41469 | 654 | 행 수 불일치 (정답 1, 예측 2) |
| compare-13 | match | 20686 | 466 |  |
| compare-14 | match | 19186 | 460 |  |
| compare-15 | mismatch | 16468 | 501 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### compare-08 — mismatch

질문: 최근 7일과 그 전 7일의 nov_mega_sale 캠페인 세션 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
SELECT 'recent_7d' AS period, SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE traffic_campaign = 'nov_mega_sale'
  AND summary_date >= current_date - 7
  AND summary_date < current_date

UNION ALL

SELECT 'previous_7d' AS period, SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE traffic_campaign = 'nov_mega_sale'
  AND summary_date >= current_date - 14
  AND summary_date < current_date - 7

ORDER BY period;
```

### compare-09 — mismatch

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
SELECT 
    CASE WHEN EXTRACT(DOW FROM summary_date)::int IN (0,6) THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    AVG(daily_sessions)::numeric AS avg_sessions_per_day
FROM (
    SELECT summary_date, SUM(sessions) AS daily_sessions
    FROM agg_user_session_daily
    WHERE summary_date >= current_date - 28
      AND summary_date < current_date
    GROUP BY summary_date
) AS d
GROUP BY day_type
ORDER BY day_type;
```

### compare-10 — llm_error

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: LLM 응답 오류 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01kg4rt8pafgt9s6wpajpk0052` service tier `on_demand` on tokens per minute (TPM): Limit 8000,

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
SELECT period,
       avg_daily_pageviews
FROM (
    SELECT 'last_month' AS period,
           AVG(daily_views) AS avg_daily_pageviews
    FROM (
        SELECT summary_date,
               SUM(page_views) AS daily_views
        FROM agg_page_daily
        WHERE summary_date >= date_trunc('month', current_date) - INTERVAL '1 month'
          AND summary_date < date_trunc('month', current_date)
        GROUP BY summary_date
    ) lm
    UNION ALL
    SELECT 'this_month' AS period,
           AVG(daily_views) AS avg_daily_pageviews
    FROM (
        SELECT summary_date,
               SUM(page_views) AS daily_views
        FROM agg_page_daily
        WHERE summary_date >= date_trunc('month', current_date)
          AND summary_date <= current_date
        GROUP BY summary_date
    ) tm
) sub
ORDER BY period;
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT
    traffic_source,
    SUM(sessions) AS sessions,
    SUM(conversions) AS conversions,
    ROUND(SUM(conversions)::numeric * 100.0 / NULLIF(SUM(sessions), 0), 2) AS conversion_rate_percent
FROM agg_traffic_hourly
WHERE summary_date >= date_trunc('week', current_date)::date - 7
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY traffic_source
HAVING SUM(sessions) >= 200
ORDER BY conversion_rate_percent DESC
LIMIT 3;
```

