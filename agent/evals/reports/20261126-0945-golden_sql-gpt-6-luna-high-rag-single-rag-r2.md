# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:45:04+09:00 / single-rag-r2
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 86.7% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: match 42, mismatch 1, rejected 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 2931, 중앙값 2032, 최대 15500
- 평균 토큰: 입력 2141, 출력 321 (추론 212)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1438 | 81 |  |
| lookup-02 | match | 1828 | 151 |  |
| lookup-03 | match | 1719 | 157 |  |
| lookup-04 | match | 1422 | 128 |  |
| lookup-05 | match | 1717 | 143 |  |
| lookup-06 | match | 2000 | 195 |  |
| lookup-07 | match | 1719 | 136 |  |
| lookup-08 | match | 1436 | 93 |  |
| lookup-09 | match | 1671 | 140 |  |
| lookup-10 | match | 2280 | 160 |  |
| lookup-11 | match | 2936 | 320 |  |
| lookup-12 | match | 1500 | 160 |  |
| lookup-13 | match | 2344 | 265 |  |
| lookup-14 | match | 2813 | 275 |  |
| compare-01 | match | 3828 | 434 |  |
| compare-02 | match | 1890 | 185 |  |
| compare-03 | match | 1828 | 195 |  |
| compare-04 | match | 2125 | 206 |  |
| compare-05 | match | 7625 | 1172 |  |
| compare-06 | match | 6469 | 853 |  |
| lookup-15 | match | 1266 | 78 |  |
| lookup-16 | match | 1438 | 109 |  |
| lookup-17 | match | 1827 | 182 |  |
| lookup-18 | match | 1390 | 109 |  |
| lookup-19 | match | 2125 | 136 |  |
| lookup-20 | match | 1297 | 119 |  |
| lookup-21 | match | 1546 | 163 |  |
| lookup-22 | match | 3219 | 275 |  |
| lookup-23 | match | 1578 | 117 |  |
| lookup-24 | match | 1547 | 121 |  |
| lookup-25 | match | 1766 | 120 |  |
| lookup-26 | match | 1561 | 111 |  |
| lookup-27 | match | 2063 | 165 |  |
| lookup-28 | match | 3344 | 313 |  |
| lookup-29 | match | 2250 | 217 |  |
| compare-07 | match | 4046 | 419 |  |
| compare-08 | match | 4000 | 528 |  |
| compare-09 | match | 5578 | 750 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | mismatch | 4265 | 497 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-11 | match | 4578 | 557 |  |
| compare-12 | match | 3797 | 399 |  |
| compare-13 | match | 3250 | 269 |  |
| compare-14 | match | 5141 | 690 |  |
| compare-15 | rejected | 15500 | 2245 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |

## 실패 문항

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/agg_traffic_hourly, table/daily_metrics, metric/sessions, metric/bounce_rate, glossary/traffic_channels, glossary/weekday, glossary/hour_of_day, example/weekly_unique_visitors

```sql
SELECT
  EXTRACT(ISODOW FROM summary_date)::int AS iso_weekday,
  SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE summary_date >= current_date - 27
  AND summary_date <= current_date
  AND traffic_medium = 'email'
GROUP BY iso_weekday
ORDER BY iso_weekday
LIMIT 1000
```

### compare-15 — rejected

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

넣은 문서: table/agg_traffic_hourly, table/agg_funnel_links_daily, metric/payment_session_rate, metric/sessions, glossary/traffic_channels, glossary/period_week, glossary/event_names, example/landing_bounce_by_source

```sql
WITH period AS (
    SELECT
        date_trunc('week', current_date)::date - 7 AS start_date,
        date_trunc('week', current_date)::date AS end_date
),
weekly_source_sessions AS (
    SELECT
        traffic_source,
        sum(sessions) AS sessions
    FROM agg_traffic_hourly
    CROSS JOIN period
    WHERE summary_date >= period.start_date
      AND summary_date < period.end_date
    GROUP BY traffic_source
    HAVING sum(sessions) >= 200
),
source_payment_rates AS (
    SELECT
        e.traffic_source,
        count(DISTINCT e.session_id) FILTER (
            WHERE e.event_name = 'is_payment'
        ) * 100.0
        / NULLIF(count(DISTINCT e.session_id), 0) AS payment_session_rate
    FROM events e
    CROSS JOIN period
    WHERE e.event_timestamp >= period.start_date::timestamp
      AND e.event_timestamp < period.end_date::timestamp
    GROUP BY e.traffic_source
)
SELECT
    w.traffic_source AS traffic_source,
    w.sessions AS sessions,
    r.payment_session_rate AS payment_session_rate_percent
FROM weekly_source_sessions w
JOIN source_payment_rates r
  ON r.traffic_source = w.traffic_source
ORDER BY payment_session_rate_percent DESC
LIMIT 3
```

