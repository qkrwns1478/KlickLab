# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:42:24+09:00 / single-prompt-r3
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **97.7%** (43/44)
- 난이도별: compare 100.0% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 43, mismatch 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 3787, 중앙값 2343, 최대 17813
- 평균 토큰: 입력 1876, 출력 430 (추론 298)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1889 | 108 |  |
| lookup-02 | match | 1954 | 135 |  |
| lookup-03 | match | 2266 | 162 |  |
| lookup-04 | match | 1969 | 162 |  |
| lookup-05 | match | 1889 | 149 |  |
| lookup-06 | match | 2172 | 204 |  |
| lookup-07 | match | 2063 | 171 |  |
| lookup-08 | match | 1577 | 141 |  |
| lookup-09 | match | 2297 | 176 |  |
| lookup-10 | match | 2561 | 227 |  |
| lookup-11 | match | 3500 | 403 |  |
| lookup-12 | match | 1625 | 172 |  |
| lookup-13 | match | 2219 | 219 |  |
| lookup-14 | match | 7530 | 997 |  |
| compare-01 | match | 4266 | 565 |  |
| compare-02 | match | 2342 | 258 |  |
| compare-03 | match | 2733 | 265 |  |
| compare-04 | match | 10202 | 1359 |  |
| compare-05 | match | 5438 | 697 |  |
| compare-06 | match | 7141 | 948 |  |
| lookup-15 | match | 1561 | 101 |  |
| lookup-16 | match | 1983 | 155 |  |
| lookup-17 | match | 2469 | 200 |  |
| lookup-18 | match | 1655 | 152 |  |
| lookup-19 | match | 1891 | 130 |  |
| lookup-20 | match | 2186 | 182 |  |
| lookup-21 | match | 1936 | 171 |  |
| lookup-22 | mismatch | 5421 | 686 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 2390 | 208 |  |
| lookup-24 | match | 1983 | 155 |  |
| lookup-25 | match | 2344 | 216 |  |
| lookup-26 | match | 2032 | 171 |  |
| lookup-27 | match | 2063 | 136 |  |
| lookup-28 | match | 3046 | 321 |  |
| lookup-29 | match | 1811 | 143 |  |
| compare-07 | match | 7952 | 1042 |  |
| compare-08 | match | 5875 | 766 |  |
| compare-09 | match | 3969 | 462 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 4780 | 480 |  |
| compare-11 | match | 9014 | 1220 |  |
| compare-12 | match | 6235 | 777 |  |
| compare-13 | match | 5405 | 724 |  |
| compare-14 | match | 3171 | 294 |  |
| compare-15 | match | 17813 | 2504 |  |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH last_week_users AS (
    SELECT
        u.client_id,
        EXISTS (
            SELECT 1
            FROM agg_daily_users AS prior
            WHERE prior.client_id = u.client_id
              AND prior.summary_date < date_trunc('week', current_date)::date - 7
        ) AS has_prior_activity
    FROM agg_daily_users AS u
    WHERE u.summary_date >= date_trunc('week', current_date)::date - 7
      AND u.summary_date < date_trunc('week', current_date)::date
    GROUP BY u.client_id
)
SELECT
    count(*) FILTER (WHERE NOT has_prior_activity) AS 신규_방문자_수,
    count(*) FILTER (WHERE has_prior_activity) AS 재방문자_수
FROM last_week_users;
```

