# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-13T10:16:59+09:00 / local-single-rag
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **86.4%** (38/44)
- 난이도별: compare 73.3% (15), lookup 93.1% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: exec_error 3, match 38, rejected 3
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 6760, 중앙값 5366, 최대 18186
- 평균 토큰: 입력 2180, 출력 530 (추론 0)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 2344 | 120 |  |
| lookup-02 | match | 3640 | 268 |  |
| lookup-03 | match | 4905 | 384 |  |
| lookup-04 | match | 4062 | 310 |  |
| lookup-05 | match | 5922 | 461 |  |
| lookup-06 | match | 8469 | 675 |  |
| lookup-07 | match | 3235 | 231 |  |
| lookup-08 | match | 5031 | 392 |  |
| lookup-09 | match | 3202 | 230 |  |
| lookup-10 | match | 7014 | 546 |  |
| lookup-11 | match | 7875 | 620 |  |
| lookup-12 | match | 4125 | 301 |  |
| lookup-13 | exec_error | 8171 | 656 | column "summary_date" does not exist |
| lookup-14 | match | 9500 | 763 |  |
| compare-01 | match | 14452 | 1165 |  |
| compare-02 | match | 4672 | 350 |  |
| compare-03 | match | 9390 | 737 |  |
| compare-04 | match | 5265 | 404 |  |
| compare-05 | exec_error | 15437 | 1267 | invalid UNION/INTERSECT/EXCEPT ORDER BY clause (힌트: Add the expression/function to every SELECT, or move the UNION into a FROM clause.) |
| compare-06 | match | 9733 | 794 |  |
| lookup-15 | match | 2656 | 185 |  |
| lookup-16 | match | 3187 | 238 |  |
| lookup-17 | match | 4218 | 318 |  |
| lookup-18 | match | 6547 | 521 |  |
| lookup-19 | match | 3890 | 290 |  |
| lookup-20 | match | 4233 | 319 |  |
| lookup-21 | match | 6375 | 502 |  |
| lookup-22 | match | 5327 | 410 |  |
| lookup-23 | match | 4155 | 305 |  |
| lookup-24 | match | 3078 | 219 |  |
| lookup-25 | match | 5358 | 418 |  |
| lookup-26 | match | 4062 | 299 |  |
| lookup-27 | match | 4562 | 343 |  |
| lookup-28 | rejected | 11405 | 924 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |
| lookup-29 | match | 4969 | 380 |  |
| compare-07 | exec_error | 5594 | 429 | column "device_type" does not exist |
| compare-08 | match | 5609 | 435 |  |
| compare-09 | match | 5672 | 440 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 8014 | 636 |  |
| compare-11 | rejected | 15250 | 1250 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |
| compare-12 | match | 6016 | 465 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 17250 | 1417 |  |
| compare-14 | match | 5375 | 410 |  |
| compare-15 | rejected | 18186 | 1495 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |

## 실패 문항

### lookup-13 — exec_error

질문: 최근 7일 페이지뷰 100회 이상인 페이지 중 평균 체류 시간(초)이 가장 긴 5개는?

사유: column "summary_date" does not exist

넣은 문서: table/daily_page_stats, table/agg_page_daily, metric/avg_session_duration, metric/page_views, glossary/period_recent_days, glossary/pages, glossary/data_rules, example/landing_bounce_by_source

```sql
SELECT
    page_path,
    SUM(page_views) AS total_page_views,
    SUM(page_views * avg_time_on_page_seconds)::numeric 
        / NULLIF(SUM(page_views), 0) AS avg_time_seconds
FROM daily_page_stats
WHERE summary_date >= current_date - 7
  AND summary_date <  current_date
GROUP BY page_path
HAVING SUM(page_views) >= 100
ORDER BY avg_time_seconds DESC
LIMIT 5;
```

### compare-05 — exec_error

질문: 최근 7일과 그 전 7일의 일평균 순 방문자 수를 비교해줘

사유: invalid UNION/INTERSECT/EXCEPT ORDER BY clause (힌트: Add the expression/function to every SELECT, or move the UNION into a FROM clause.)

넣은 문서: table/agg_daily_users, table/daily_metrics, metric/unique_visitors, metric/new_returning_visitors, glossary/period_recent_days, glossary/period_week, glossary/weekday, example/cart_to_checkout_daily

```sql
WITH recent AS (
    SELECT
        summary_date,
        count(*) AS daily_visitors
    FROM agg_daily_users
    WHERE summary_date >= current_date - 7
      AND summary_date < current_date
    GROUP BY summary_date
),
previous AS (
    SELECT
        summary_date,
        count(*) AS daily_visitors
    FROM agg_daily_users
    WHERE summary_date >= current_date - 14
      AND summary_date < current_date - 7
    GROUP BY summary_date
)
SELECT 'recent 7 days'  AS period, ROUND(AVG(daily_visitors)::numeric, 2) AS avg_daily_visitors
FROM recent
UNION ALL
SELECT 'previous 7 days' AS period, ROUND(AVG(daily_visitors)::numeric, 2) AS avg_daily_visitors
FROM previous
ORDER BY CASE WHEN period = 'recent 7 days' THEN 1 ELSE 2 END;
```

### lookup-28 — rejected

질문: 15일 전 모바일 기기의 결제 완료 건수는?

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_event_daily, table/agg_user_session_hourly, metric/payments, metric/revenue, glossary/devices, glossary/event_names, glossary/period_day, example/daily_revenue_trend

```sql
SELECT COUNT(*) AS payment_count
FROM events
WHERE event_name = 'is_payment'
  AND DATE(event_timestamp AT TIME ZONE 'Asia/Seoul') = current_date - 15
  AND device_type = 'mobile';
```

### compare-07 — exec_error

질문: 지난주 대비 이번 주 기기 유형별 세션 수를 비교해줘

사유: column "device_type" does not exist

넣은 문서: table/agg_user_session_hourly, table/daily_user_distribution, metric/sessions, metric/payment_session_rate, glossary/period_week, glossary/devices, glossary/data_rules, example/device_checkout_completion_events

```sql
SELECT
    device_type,
    SUM(sessions) FILTER (
        WHERE summary_date >= date_trunc('week', current_date)::date
    ) AS this_week_sessions,
    SUM(sessions) FILTER (
        WHERE summary_date >= date_trunc('week', current_date)::date - INTERVAL '7 days'
          AND summary_date < date_trunc('week', current_date)::date
    ) AS last_week_sessions
FROM agg_user_session_daily
GROUP BY device_type
ORDER BY this_week_sessions DESC
LIMIT 1000;
```

### compare-11 — rejected

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_event_daily, table/agg_funnel_links_daily, metric/payments, metric/payment_session_rate, glossary/period_day, glossary/event_names, glossary/devices, example/daily_revenue_trend

```sql
SELECT
    date(event_timestamp) AS summary_date,
    device_type,
    COUNT(*) AS payment_count
FROM events
WHERE event_name = 'is_payment'
  AND event_timestamp >= current_date - 15
  AND event_timestamp < current_date - 13
GROUP BY summary_date, device_type
ORDER BY summary_date DESC, device_type
LIMIT 1000;
```

### compare-15 — rejected

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_traffic_hourly, table/agg_funnel_links_daily, metric/payment_session_rate, metric/sessions, glossary/traffic_channels, glossary/period_week, glossary/event_names, example/landing_bounce_by_source

```sql
WITH last_week_sessions AS (
  SELECT traffic_source,
         SUM(sessions) AS total_sessions
  FROM agg_traffic_hourly
  WHERE summary_date >= date_trunc('week', current_date)::date - INTERVAL '7 days'
    AND summary_date < date_trunc('week', current_date)::date
  GROUP BY traffic_source
),
last_week_payments AS (
  SELECT traffic_source,
         COUNT(DISTINCT session_id) AS payment_sessions
  FROM events
  WHERE event_name = 'is_payment'
    AND event_timestamp >= date_trunc('week', current_date)::date - INTERVAL '7 days'
    AND event_timestamp < date_trunc('week', current_date)::date
  GROUP BY traffic_source
)
SELECT ls.traffic_source,
       ls.total_sessions,
       COALESCE(lp.payment_sessions, 0) AS payment_sessions,
       100.0 * COALESCE(lp.payment_sessions, 0) / NULLIF(ls.total_sessions, 0) AS payment_rate
FROM last_week_sessions ls
LEFT JOIN last_week_payments lp USING (traffic_source)
WHERE ls.total_sessions >= 200
ORDER BY payment_rate DESC
LIMIT 3;
```

