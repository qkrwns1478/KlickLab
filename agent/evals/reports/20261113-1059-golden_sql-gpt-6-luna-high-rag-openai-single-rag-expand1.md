# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-13T10:59:20+09:00 / openai-single-rag-expand1
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **93.2%** (41/44)
- 난이도별: compare 80.0% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: exec_error 1, match 41, mismatch 1, rejected 1
- 지연(ms): 평균 5006, 중앙값 3335, 최대 16062
- 평균 토큰: 입력 2323, 출력 333 (추론 207)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1860 | 76 |  |
| lookup-02 | match | 2781 | 133 |  |
| lookup-03 | match | 2062 | 111 |  |
| lookup-04 | match | 3094 | 142 |  |
| lookup-05 | match | 2936 | 141 |  |
| lookup-06 | match | 2765 | 196 |  |
| lookup-07 | match | 2750 | 141 |  |
| lookup-08 | match | 2858 | 129 |  |
| lookup-09 | match | 2702 | 132 |  |
| lookup-10 | match | 3641 | 164 |  |
| lookup-11 | match | 2969 | 168 |  |
| lookup-12 | match | 2702 | 162 |  |
| lookup-13 | match | 3327 | 270 |  |
| lookup-14 | match | 5077 | 369 |  |
| compare-01 | match | 16062 | 1224 |  |
| compare-02 | match | 3188 | 193 |  |
| compare-03 | match | 6672 | 478 |  |
| compare-04 | match | 4234 | 259 |  |
| compare-05 | match | 10641 | 748 |  |
| compare-06 | match | 9296 | 695 |  |
| lookup-15 | match | 2233 | 88 |  |
| lookup-16 | match | 2500 | 118 |  |
| lookup-17 | match | 3797 | 173 |  |
| lookup-18 | match | 3125 | 116 |  |
| lookup-19 | match | 2797 | 118 |  |
| lookup-20 | match | 2858 | 117 |  |
| lookup-21 | match | 3077 | 158 |  |
| lookup-22 | match | 4172 | 277 |  |
| lookup-23 | match | 4625 | 269 |  |
| lookup-24 | match | 3343 | 132 |  |
| lookup-25 | match | 2655 | 113 |  |
| lookup-26 | match | 3233 | 154 |  |
| lookup-27 | match | 3297 | 150 |  |
| lookup-28 | match | 5016 | 441 |  |
| lookup-29 | match | 6235 | 362 |  |
| compare-07 | match | 6436 | 770 |  |
| compare-08 | match | 7014 | 527 |  |
| compare-09 | exec_error | 9890 | 577 | column "day_type" does not exist |
| compare-10 | match | 4125 | 225 |  |
| compare-11 | rejected | 9000 | 731 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |
| compare-12 | mismatch | 10640 | 756 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-13 | match | 6953 | 597 |  |
| compare-14 | match | 11531 | 990 |  |
| compare-15 | match | 10078 | 774 |  |

## 실패 문항

### compare-09 — exec_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: column "day_type" does not exist

넣은 문서: table/agg_user_session_daily, table/daily_metrics, metric/sessions, metric/avg_session_duration, glossary/weekday, glossary/period_recent_days, glossary/hour_of_day, example/cart_to_checkout_daily, table/agg_traffic_hourly

```sql
WITH calendar AS (
    SELECT generate_series(
        current_date - 28,
        current_date - 1,
        interval '1 day'
    )::date AS summary_date
),
daily_sessions AS (
    SELECT
        c.summary_date,
        COALESCE(SUM(a.sessions), 0) AS sessions
    FROM calendar c
    LEFT JOIN agg_user_session_daily a
        ON a.summary_date = c.summary_date
    GROUP BY c.summary_date
)
SELECT
    CASE
        WHEN EXTRACT(ISODOW FROM summary_date) IN (6, 7) THEN '주말'
        ELSE '평일'
    END AS day_type,
    AVG(sessions) AS avg_sessions_per_day
FROM daily_sessions
GROUP BY day_type
ORDER BY CASE day_type WHEN '평일' THEN 1 ELSE 2 END
```

### compare-11 — rejected

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_event_daily, table/agg_funnel_links_daily, metric/payments, metric/payment_session_rate, glossary/period_day, glossary/event_names, glossary/devices, example/daily_revenue_trend, table/events

```sql
WITH period AS (
    SELECT
        (current_date - 15)::timestamp AT TIME ZONE 'Asia/Seoul' AS start_15,
        (current_date - 14)::timestamp AT TIME ZONE 'Asia/Seoul' AS start_14,
        (current_date - 13)::timestamp AT TIME ZONE 'Asia/Seoul' AS end_period
)
SELECT
    e.device_type AS device_type,
    count(*) FILTER (
        WHERE e.timestamp >= p.start_15 AND e.timestamp < p.start_14
    ) AS payments_15_days_ago,
    count(*) FILTER (
        WHERE e.timestamp >= p.start_14 AND e.timestamp < p.end_period
    ) AS payments_14_days_ago
FROM events e
CROSS JOIN period p
WHERE e.event_name = 'is_payment'
  AND e.timestamp >= p.start_15
  AND e.timestamp < p.end_period
GROUP BY e.device_type
ORDER BY e.device_type
LIMIT 1000
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/daily_page_stats, table/agg_page_daily, metric/page_views, metric/unique_visitors, glossary/period_month, glossary/pages, glossary/period_week, example/city_sessions_month_compare, table/agg_daily_users

```sql
WITH calendar AS (
    SELECT day::date AS summary_date
    FROM generate_series(
        (date_trunc('month', current_date) - interval '1 month')::date,
        current_date,
        interval '1 day'
    ) AS day
),
daily_page_views AS (
    SELECT summary_date, sum(page_views) AS page_views
    FROM agg_page_daily
    WHERE summary_date >= (date_trunc('month', current_date) - interval '1 month')::date
      AND summary_date < (date_trunc('month', current_date) + interval '1 month')::date
    GROUP BY summary_date
)
SELECT
    avg(coalesce(d.page_views, 0)) FILTER (
        WHERE c.summary_date < date_trunc('month', current_date)::date
    ) AS last_month_avg_daily_page_views,
    avg(coalesce(d.page_views, 0)) FILTER (
        WHERE c.summary_date >= date_trunc('month', current_date)::date
    ) AS this_month_avg_daily_page_views
FROM calendar c
LEFT JOIN daily_page_views d USING (summary_date)
```

