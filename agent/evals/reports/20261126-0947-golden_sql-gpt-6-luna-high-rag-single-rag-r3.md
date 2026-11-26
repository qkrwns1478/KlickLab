# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:47:45+09:00 / single-rag-r3
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **97.7%** (43/44)
- 난이도별: compare 93.3% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: exec_error 1, match 43
- 지연(ms): 평균 3127, 중앙값 2274, 최대 13859
- 평균 토큰: 입력 2141, 출력 333 (추론 220)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1717 | 70 |  |
| lookup-02 | match | 2452 | 212 |  |
| lookup-03 | match | 1905 | 142 |  |
| lookup-04 | match | 2186 | 153 |  |
| lookup-05 | match | 2578 | 217 |  |
| lookup-06 | match | 3719 | 181 |  |
| lookup-07 | match | 2297 | 144 |  |
| lookup-08 | match | 1655 | 103 |  |
| lookup-09 | match | 1530 | 117 |  |
| lookup-10 | match | 2578 | 261 |  |
| lookup-11 | match | 3328 | 346 |  |
| lookup-12 | match | 1657 | 159 |  |
| lookup-13 | match | 2000 | 233 |  |
| lookup-14 | match | 3500 | 361 |  |
| compare-01 | match | 5546 | 721 |  |
| compare-02 | match | 1953 | 195 |  |
| compare-03 | match | 3250 | 357 |  |
| compare-04 | match | 3282 | 332 |  |
| compare-05 | match | 5750 | 867 |  |
| compare-06 | match | 5686 | 803 |  |
| lookup-15 | match | 1858 | 127 |  |
| lookup-16 | match | 1546 | 119 |  |
| lookup-17 | match | 1530 | 138 |  |
| lookup-18 | match | 1858 | 136 |  |
| lookup-19 | match | 1875 | 106 |  |
| lookup-20 | match | 1359 | 129 |  |
| lookup-21 | match | 2217 | 156 |  |
| lookup-22 | match | 2686 | 294 |  |
| lookup-23 | match | 1936 | 150 |  |
| lookup-24 | match | 1936 | 127 |  |
| lookup-25 | match | 1875 | 123 |  |
| lookup-26 | match | 1655 | 154 |  |
| lookup-27 | match | 1969 | 157 |  |
| lookup-28 | match | 2250 | 238 |  |
| lookup-29 | match | 1484 | 107 |  |
| compare-07 | match | 7250 | 876 |  |
| compare-08 | match | 4734 | 635 |  |
| compare-09 | exec_error | 4811 | 591 | column "day_type" does not exist |
| compare-10 | match | 3844 | 437 |  |
| compare-11 | match | 7750 | 987 |  |
| compare-12 | match | 2858 | 296 |  |
| compare-13 | match | 3313 | 374 |  |
| compare-14 | match | 2578 | 213 |  |
| compare-15 | match | 13859 | 2007 |  |

## 실패 문항

### compare-09 — exec_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: column "day_type" does not exist

넣은 문서: table/agg_user_session_daily, table/daily_metrics, metric/sessions, metric/avg_session_duration, glossary/weekday, glossary/period_recent_days, glossary/hour_of_day, example/cart_to_checkout_daily

```sql
WITH calendar AS (
    SELECT generate_series(
        current_date - 28,
        current_date - 1,
        interval '1 day'
    )::date AS summary_date
),
daily_sessions AS (
    SELECT c.summary_date,
           coalesce(sum(a.sessions), 0) AS sessions
    FROM calendar c
    LEFT JOIN agg_user_session_daily a
        ON a.summary_date = c.summary_date
    GROUP BY c.summary_date
)
SELECT CASE
           WHEN extract(isodow FROM summary_date) IN (6, 7) THEN '주말'
           ELSE '평일'
       END AS day_type,
       avg(sessions) AS avg_daily_sessions,
       count(*) AS day_count
FROM daily_sessions
GROUP BY day_type
ORDER BY CASE day_type WHEN '평일' THEN 1 ELSE 2 END
```

