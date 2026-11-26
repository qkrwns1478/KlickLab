# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:45:04+09:00 / single-rag-expand1-r2
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **90.9%** (40/44)
- 난이도별: compare 80.0% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: exec_error 1, match 40, mismatch 2, rejected 1
- 지연(ms): 평균 3082, 중앙값 2156, 최대 9625
- 평균 토큰: 입력 2348, 출력 340 (추론 230)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1592 | 85 |  |
| lookup-02 | match | 1984 | 126 |  |
| lookup-03 | match | 1905 | 134 |  |
| lookup-04 | match | 1422 | 131 |  |
| lookup-05 | match | 1547 | 131 |  |
| lookup-06 | match | 1891 | 212 |  |
| lookup-07 | match | 1828 | 135 |  |
| lookup-08 | match | 2155 | 150 |  |
| lookup-09 | match | 1625 | 128 |  |
| lookup-10 | match | 2311 | 173 |  |
| lookup-11 | match | 3046 | 323 |  |
| lookup-12 | match | 1625 | 156 |  |
| lookup-13 | match | 2094 | 214 |  |
| lookup-14 | mismatch | 4141 | 502 | 행 수 불일치 (정답 2, 예측 3) |
| compare-01 | match | 9625 | 1484 |  |
| compare-02 | match | 1890 | 208 |  |
| compare-03 | match | 2483 | 241 |  |
| compare-04 | match | 2157 | 193 |  |
| compare-05 | match | 6782 | 953 |  |
| compare-06 | match | 5234 | 668 |  |
| lookup-15 | match | 1500 | 91 |  |
| lookup-16 | match | 1515 | 120 |  |
| lookup-17 | match | 2266 | 184 |  |
| lookup-18 | match | 1532 | 128 |  |
| lookup-19 | match | 1407 | 103 |  |
| lookup-20 | match | 1733 | 145 |  |
| lookup-21 | match | 2094 | 167 |  |
| lookup-22 | match | 3546 | 388 |  |
| lookup-23 | match | 3514 | 388 |  |
| lookup-24 | match | 1890 | 119 |  |
| lookup-25 | match | 1610 | 96 |  |
| lookup-26 | match | 1625 | 124 |  |
| lookup-27 | match | 2188 | 180 |  |
| lookup-28 | match | 5842 | 756 |  |
| lookup-29 | match | 1844 | 108 |  |
| compare-07 | match | 2719 | 294 |  |
| compare-08 | match | 4047 | 305 |  |
| compare-09 | exec_error | 6313 | 795 | column "구분" does not exist |
| compare-10 | mismatch | 4936 | 525 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-11 | match | 7140 | 1053 |  |
| compare-12 | match | 3546 | 477 |  |
| compare-13 | match | 2780 | 258 |  |
| compare-14 | match | 3984 | 512 |  |
| compare-15 | rejected | 8702 | 1300 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |

## 실패 문항

### lookup-14 — mismatch

질문: 15일 전 기기 유형별로 /checkout/success 페이지를 본 세션 수는?

사유: 행 수 불일치 (정답 2, 예측 3)

넣은 문서: table/agg_page_daily, table/agg_user_session_hourly, metric/sessions, metric/page_transition_rate, glossary/pages, glossary/period_day, glossary/devices, example/device_checkout_completion_events, table/agg_traffic_hourly

```sql
WITH session_pages AS (
    SELECT
        session_id,
        min(device_type) AS device_type,
        bool_or(page_path = '/checkout/success') AS viewed_success
    FROM events
    WHERE event_name = 'page_view'
      AND timestamp >= current_date - 15
      AND timestamp < current_date - 14
    GROUP BY session_id
)
SELECT
    device_type,
    count(*) FILTER (WHERE viewed_success) AS checkout_success_sessions
FROM session_pages
GROUP BY device_type
ORDER BY device_type
LIMIT 1000
```

### compare-09 — exec_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: column "구분" does not exist

넣은 문서: table/agg_user_session_daily, table/daily_metrics, metric/sessions, metric/avg_session_duration, glossary/weekday, glossary/period_recent_days, glossary/hour_of_day, example/cart_to_checkout_daily, table/agg_traffic_hourly

```sql
WITH dates AS (
    SELECT current_date - n AS summary_date
    FROM generate_series(1, 28) AS g(n)
),
daily_sessions AS (
    SELECT summary_date, sum(sessions) AS sessions
    FROM agg_user_session_daily
    WHERE summary_date >= current_date - 28
      AND summary_date < current_date
    GROUP BY summary_date
)
SELECT
    CASE
        WHEN extract(isodow FROM d.summary_date) IN (6, 7) THEN '주말'
        ELSE '평일'
    END AS 구분,
    avg(coalesce(ds.sessions, 0)) AS 하루_평균_세션_수,
    count(*) AS 일수
FROM dates d
LEFT JOIN daily_sessions ds USING (summary_date)
GROUP BY 구분
ORDER BY CASE 구분 WHEN '평일' THEN 1 ELSE 2 END
```

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/agg_traffic_hourly, table/daily_metrics, metric/sessions, metric/bounce_rate, glossary/traffic_channels, glossary/weekday, glossary/hour_of_day, example/weekly_unique_visitors

```sql
SELECT
  EXTRACT(ISODOW FROM summary_date)::integer AS iso_weekday,
  SUM(sessions) AS email_sessions
FROM agg_traffic_hourly
WHERE summary_date >= current_date - 27
  AND summary_date < current_date + 1
  AND traffic_medium = 'email'
GROUP BY iso_weekday
ORDER BY iso_weekday
```

### compare-15 — rejected

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_traffic_hourly, table/agg_funnel_links_daily, metric/payment_session_rate, metric/sessions, glossary/traffic_channels, glossary/period_week, glossary/event_names, example/landing_bounce_by_source, table/events

```sql
WITH week_bounds AS (
    SELECT date_trunc('week', current_date)::date AS this_week_start
),
source_sessions AS (
    SELECT
        t.traffic_source,
        sum(t.sessions) AS sessions
    FROM agg_traffic_hourly AS t
    CROSS JOIN week_bounds AS w
    WHERE t.summary_date >= w.this_week_start - 7
      AND t.summary_date < w.this_week_start
    GROUP BY t.traffic_source
    HAVING sum(t.sessions) >= 200
),
source_payment_rates AS (
    SELECT
        e.traffic_source,
        count(DISTINCT e.session_id) FILTER (WHERE e.event_name = 'is_payment') * 100.0
            / NULLIF(count(DISTINCT e.session_id), 0) AS payment_session_rate_pct
    FROM events AS e
    CROSS JOIN week_bounds AS w
    WHERE e.timestamp >= ((w.this_week_start - 7)::timestamp AT TIME ZONE 'Asia/Seoul')
      AND e.timestamp < (w.this_week_start::timestamp AT TIME ZONE 'Asia/Seoul')
    GROUP BY e.traffic_source
)
SELECT
    s.traffic_source,
    s.sessions AS sessions,
    r.payment_session_rate_pct AS payment_session_rate_pct
FROM source_sessions AS s
JOIN source_payment_rates AS r
  ON r.traffic_source = s.traffic_source
ORDER BY r.payment_session_rate_pct DESC, s.traffic_source
LIMIT 3
```

