# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-13T10:55:13+09:00 / openai-single-rag
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **93.2%** (41/44)
- 난이도별: compare 80.0% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: match 41, mismatch 3
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 4993, 중앙값 3429, 최대 18655
- 평균 토큰: 입력 2116, 출력 336 (추론 218)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1983 | 79 |  |
| lookup-02 | match | 1984 | 121 |  |
| lookup-03 | match | 2922 | 134 |  |
| lookup-04 | match | 2109 | 148 |  |
| lookup-05 | match | 3000 | 150 |  |
| lookup-06 | match | 2734 | 194 |  |
| lookup-07 | match | 2938 | 118 |  |
| lookup-08 | match | 3452 | 137 |  |
| lookup-09 | match | 2562 | 154 |  |
| lookup-10 | match | 2327 | 152 |  |
| lookup-11 | match | 5171 | 442 |  |
| lookup-12 | match | 2422 | 161 |  |
| lookup-13 | match | 3641 | 213 |  |
| lookup-14 | match | 5391 | 391 |  |
| compare-01 | match | 6514 | 549 |  |
| compare-02 | match | 2922 | 191 |  |
| compare-03 | match | 3047 | 202 |  |
| compare-04 | match | 3984 | 199 |  |
| compare-05 | match | 8375 | 639 |  |
| compare-06 | match | 12219 | 786 |  |
| lookup-15 | match | 7250 | 106 |  |
| lookup-16 | match | 2061 | 114 |  |
| lookup-17 | match | 2562 | 187 |  |
| lookup-18 | match | 2061 | 121 |  |
| lookup-19 | match | 2484 | 136 |  |
| lookup-20 | match | 2563 | 123 |  |
| lookup-21 | match | 3500 | 159 |  |
| lookup-22 | match | 4452 | 318 |  |
| lookup-23 | match | 3000 | 175 |  |
| lookup-24 | match | 2610 | 142 |  |
| lookup-25 | match | 2672 | 113 |  |
| lookup-26 | match | 3108 | 157 |  |
| lookup-27 | match | 3406 | 201 |  |
| lookup-28 | match | 7844 | 573 |  |
| lookup-29 | match | 6984 | 460 |  |
| compare-07 | match | 13484 | 1218 |  |
| compare-08 | match | 5796 | 501 |  |
| compare-09 | match | 6593 | 510 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | mismatch | 7594 | 484 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-11 | mismatch | 6375 | 439 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | mismatch | 18655 | 1247 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-13 | match | 4125 | 306 |  |
| compare-14 | match | 6094 | 391 |  |
| compare-15 | match | 14734 | 1457 |  |

## 실패 문항

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/agg_traffic_hourly, table/daily_metrics, metric/sessions, metric/bounce_rate, glossary/traffic_channels, glossary/weekday, glossary/period_recent_days, example/weekly_unique_visitors

```sql
WITH daily_email_sessions AS (
    SELECT
        summary_date,
        EXTRACT(ISODOW FROM summary_date)::int AS iso_weekday,
        SUM(sessions) AS daily_sessions
    FROM agg_traffic_hourly
    WHERE summary_date >= current_date - 28
      AND summary_date < current_date
      AND traffic_medium = 'email'
    GROUP BY summary_date
)
SELECT
    iso_weekday,
    AVG(daily_sessions) AS avg_daily_sessions
FROM daily_email_sessions
GROUP BY iso_weekday
ORDER BY iso_weekday
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

넣은 문서: table/agg_event_daily, table/agg_funnel_links_daily, metric/payments, metric/payment_session_rate, glossary/period_day, glossary/event_names, glossary/devices, example/daily_revenue_trend

```sql
SELECT
    e.timestamp::date AS 날짜,
    e.device_type AS 기기_유형,
    count(*) AS 결제_완료_건수
FROM events e
WHERE e.event_name = 'is_payment'
  AND e.timestamp >= current_date - 15
  AND e.timestamp < current_date - 13
GROUP BY e.timestamp::date, e.device_type
ORDER BY 날짜, 기기_유형
LIMIT 1000
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/daily_page_stats, table/agg_page_daily, metric/page_views, metric/unique_visitors, glossary/period_month, glossary/pages, glossary/period_week, example/city_sessions_month_compare

```sql
WITH bounds AS (
    SELECT (date_trunc('month', current_date) - interval '1 month')::date AS last_month_start,
           date_trunc('month', current_date)::date AS this_month_start,
           current_date AS today
),
calendar AS (
    SELECT '지난달' AS period,
           gs.day::date AS summary_date
    FROM bounds b
    CROSS JOIN LATERAL generate_series(
        b.last_month_start::timestamp,
        (b.this_month_start - 1)::timestamp,
        interval '1 day'
    ) AS gs(day)

    UNION ALL

    SELECT '이번 달' AS period,
           gs.day::date AS summary_date
    FROM bounds b
    CROSS JOIN LATERAL generate_series(
        b.this_month_start::timestamp,
        b.today::timestamp,
        interval '1 day'
    ) AS gs(day)
),
daily_page_views AS (
    SELECT summary_date,
           sum(page_views) AS page_views
    FROM agg_page_daily
    WHERE summary_date >= (date_trunc('month', current_date) - interval '1 month')::date
      AND summary_date <= current_date
    GROUP BY summary_date
)
SELECT avg(coalesce(d.page_views, 0)) FILTER (WHERE c.period = '지난달') AS 지난달_일평균_페이지뷰,
       avg(coalesce(d.page_views, 0)) FILTER (WHERE c.period = '이번 달') AS 이번달_일평균_페이지뷰
FROM calendar c
LEFT JOIN daily_page_views d USING (summary_date)
```

