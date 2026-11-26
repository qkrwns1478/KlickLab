# golden SQL 평가 — k-exaone_v2.5 (reasoning_effort=high)

- 실행: 2026-11-11T13:49:22+09:00
- 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **95.0%** (19/20)
- 난이도별: compare 83.3% (6), lookup 100.0% (14)
- 상태: match 19, mismatch 1
- 생성 지연(ms): 평균 51806, 중앙값 40086, 최대 130266
- 평균 토큰: 입력 1842, 출력 1263 (추론 1134)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 12719 | 237 |  |
| lookup-02 | match | 21422 | 562 |  |
| lookup-03 | match | 22546 | 504 |  |
| lookup-04 | match | 43515 | 1026 |  |
| lookup-05 | match | 35608 | 834 |  |
| lookup-06 | match | 30422 | 798 |  |
| lookup-07 | match | 13516 | 396 |  |
| lookup-08 | match | 90530 | 1515 |  |
| lookup-09 | match | 34312 | 797 |  |
| lookup-10 | match | 40422 | 957 |  |
| lookup-11 | match | 70155 | 1587 |  |
| lookup-12 | match | 28985 | 717 |  |
| lookup-13 | match | 32000 | 822 |  |
| lookup-14 | match | 118406 | 3175 |  |
| compare-01 | match | 70546 | 1835 |  |
| compare-02 | match | 113327 | 2947 |  |
| compare-03 | match | 42561 | 1011 |  |
| compare-04 | match | 45108 | 1149 |  |
| compare-05 | mismatch | 39750 | 899 | 행 수 불일치 (정답 1, 예측 2) |
| compare-06 | match | 130266 | 3491 |  |

## 실패 문항

### compare-05 — mismatch

질문: 최근 7일과 그 전 7일의 일평균 순 방문자 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

넣은 문서: table/agg_daily_users, table/daily_metrics, metric/unique_visitors, metric/new_returning_visitors, glossary/period_recent_days, glossary/period_week, glossary/weekday, example/cart_to_checkout_daily

```sql
WITH daily_visitors AS (
  SELECT summary_date, count(*) AS daily_visitors
  FROM agg_daily_users
  WHERE summary_date >= current_date - 14
    AND summary_date < current_date
  GROUP BY summary_date
),
period_avg AS (
  SELECT
    '최근 7일' AS period,
    avg(daily_visitors) FILTER (WHERE summary_date >= current_date - 7) AS avg_daily_visitors
  FROM daily_visitors
  UNION ALL
  SELECT
    '그 전 7일' AS period,
    avg(daily_visitors) FILTER (
      WHERE summary_date >= current_date - 14
        AND summary_date < current_date - 7
    ) AS avg_daily_visitors
  FROM daily_visitors
)
SELECT
  period,
  round(avg_daily_visitors, 1) AS avg_daily_visitors
FROM period_avg
ORDER BY period;
```

