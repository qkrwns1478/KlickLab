# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:42:24+09:00 / single-prompt-r1
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **97.7%** (43/44)
- 난이도별: compare 100.0% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: exec_error 1, match 43
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 3644, 중앙값 2313, 최대 17217
- 평균 토큰: 입력 1876, 출력 413 (추론 289)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1860 | 78 |  |
| lookup-02 | match | 2344 | 122 |  |
| lookup-03 | match | 1625 | 124 |  |
| lookup-04 | match | 1733 | 128 |  |
| lookup-05 | match | 1922 | 155 |  |
| lookup-06 | match | 2313 | 190 |  |
| lookup-07 | match | 1952 | 151 |  |
| lookup-08 | match | 1797 | 171 |  |
| lookup-09 | match | 1608 | 127 |  |
| lookup-10 | match | 2280 | 209 |  |
| lookup-11 | match | 3577 | 437 |  |
| lookup-12 | match | 2063 | 189 |  |
| lookup-13 | match | 2313 | 226 |  |
| lookup-14 | match | 2686 | 283 |  |
| compare-01 | match | 4969 | 629 |  |
| compare-02 | match | 2844 | 285 |  |
| compare-03 | match | 3030 | 313 |  |
| compare-04 | match | 12672 | 1705 |  |
| compare-05 | match | 5391 | 728 |  |
| compare-06 | match | 8422 | 1113 |  |
| lookup-15 | match | 1891 | 150 |  |
| lookup-16 | match | 1858 | 142 |  |
| lookup-17 | match | 3045 | 240 |  |
| lookup-18 | match | 2313 | 202 |  |
| lookup-19 | match | 1375 | 121 |  |
| lookup-20 | match | 2172 | 189 |  |
| lookup-21 | match | 1889 | 166 |  |
| lookup-22 | exec_error | 7702 | 982 | 실행 시간이 5000ms 를 넘었습니다. 기간을 줄이거나 집계 테이블을 사용하세요. |
| lookup-23 | match | 1983 | 163 |  |
| lookup-24 | match | 2000 | 168 |  |
| lookup-25 | match | 2000 | 172 |  |
| lookup-26 | match | 1561 | 158 |  |
| lookup-27 | match | 1750 | 152 |  |
| lookup-28 | match | 2797 | 258 |  |
| lookup-29 | match | 1578 | 130 |  |
| compare-07 | match | 4766 | 640 |  |
| compare-08 | match | 4217 | 572 |  |
| compare-09 | match | 3844 | 393 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 2078 | 192 |  |
| compare-11 | match | 8641 | 1195 |  |
| compare-12 | match | 8641 | 1097 |  |
| compare-13 | match | 5155 | 645 |  |
| compare-14 | match | 2469 | 236 |  |
| compare-15 | match | 17217 | 2451 |  |

## 실패 문항

### lookup-22 — exec_error

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 실행 시간이 5000ms 를 넘었습니다. 기간을 줄이거나 집계 테이블을 사용하세요.

```sql
WITH bounds AS (
    SELECT
        date_trunc('week', current_date)::date - 7 AS week_start,
        date_trunc('week', current_date)::date AS week_end
),
week_visitors AS (
    SELECT DISTINCT d.client_id
    FROM agg_daily_users d
    CROSS JOIN bounds b
    WHERE d.summary_date >= b.week_start
      AND d.summary_date < b.week_end
),
classified AS (
    SELECT
        w.client_id,
        EXISTS (
            SELECT 1
            FROM agg_daily_users prior
            CROSS JOIN bounds b
            WHERE prior.client_id = w.client_id
              AND prior.summary_date < b.week_start
        ) AS visited_before
    FROM week_visitors w
)
SELECT
    COUNT(*) FILTER (WHERE NOT visited_before) AS new_visitors,
    COUNT(*) FILTER (WHERE visited_before) AS returning_visitors
FROM classified;
```

