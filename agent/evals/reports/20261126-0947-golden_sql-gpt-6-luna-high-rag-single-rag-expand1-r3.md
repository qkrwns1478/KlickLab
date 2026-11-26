# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:47:45+09:00 / single-rag-expand1-r3
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 86.7% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: exec_error 1, match 42, mismatch 1
- 지연(ms): 평균 2981, 중앙값 2296, 최대 10796
- 평균 토큰: 입력 2348, 출력 323 (추론 214)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 3077 | 82 |  |
| lookup-02 | match | 1765 | 108 |  |
| lookup-03 | match | 1516 | 119 |  |
| lookup-04 | match | 1890 | 140 |  |
| lookup-05 | match | 1483 | 136 |  |
| lookup-06 | match | 1844 | 181 |  |
| lookup-07 | match | 2311 | 152 |  |
| lookup-08 | match | 1375 | 108 |  |
| lookup-09 | match | 3077 | 157 |  |
| lookup-10 | match | 2280 | 195 |  |
| lookup-11 | match | 2092 | 169 |  |
| lookup-12 | match | 1813 | 162 |  |
| lookup-13 | match | 2344 | 280 |  |
| lookup-14 | match | 2577 | 266 |  |
| compare-01 | match | 4796 | 646 |  |
| compare-02 | match | 1828 | 194 |  |
| compare-03 | match | 5594 | 676 |  |
| compare-04 | match | 2657 | 285 |  |
| compare-05 | match | 10796 | 1687 |  |
| compare-06 | match | 4827 | 676 |  |
| lookup-15 | match | 1469 | 129 |  |
| lookup-16 | match | 1703 | 108 |  |
| lookup-17 | match | 2234 | 152 |  |
| lookup-18 | match | 1625 | 132 |  |
| lookup-19 | match | 1453 | 107 |  |
| lookup-20 | match | 1813 | 167 |  |
| lookup-21 | match | 2188 | 161 |  |
| lookup-22 | match | 5390 | 673 |  |
| lookup-23 | match | 1546 | 128 |  |
| lookup-24 | match | 1405 | 124 |  |
| lookup-25 | match | 1422 | 86 |  |
| lookup-26 | match | 1844 | 142 |  |
| lookup-27 | match | 2155 | 182 |  |
| lookup-28 | match | 4875 | 516 |  |
| lookup-29 | match | 3108 | 305 |  |
| compare-07 | match | 5171 | 690 |  |
| compare-08 | match | 4047 | 502 |  |
| compare-09 | exec_error | 4140 | 572 | column "day_type" does not exist |
| compare-10 | mismatch | 4671 | 504 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-11 | match | 4296 | 514 |  |
| compare-12 | match | 3735 | 447 |  |
| compare-13 | match | 3186 | 437 |  |
| compare-14 | match | 2563 | 219 |  |
| compare-15 | match | 5172 | 778 |  |

## 실패 문항

### compare-09 — exec_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: column "day_type" does not exist

넣은 문서: table/agg_user_session_daily, table/daily_metrics, metric/sessions, metric/avg_session_duration, glossary/weekday, glossary/period_recent_days, glossary/hour_of_day, example/cart_to_checkout_daily, table/agg_traffic_hourly

```sql
WITH dates AS (
    SELECT generate_series(
        current_date - 28,
        current_date - 1,
        interval '1 day'
    )::date AS summary_date
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
    END AS day_type,
    avg(coalesce(s.sessions, 0)) AS avg_daily_sessions
FROM dates d
LEFT JOIN daily_sessions s USING (summary_date)
GROUP BY day_type
ORDER BY CASE WHEN day_type = '평일' THEN 1 ELSE 2 END
```

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/agg_traffic_hourly, table/daily_metrics, metric/sessions, metric/bounce_rate, glossary/traffic_channels, glossary/weekday, glossary/hour_of_day, example/weekly_unique_visitors

```sql
SELECT
  extract(isodow FROM summary_date)::integer AS iso_weekday,
  sum(sessions) AS email_sessions
FROM agg_traffic_hourly
WHERE summary_date >= current_date - 27
  AND summary_date < current_date + 1
  AND traffic_medium = 'email'
GROUP BY iso_weekday
ORDER BY iso_weekday
```

