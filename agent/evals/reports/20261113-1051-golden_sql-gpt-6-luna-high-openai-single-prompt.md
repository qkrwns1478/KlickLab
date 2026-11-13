# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-13T10:51:45+09:00 / openai-single-prompt
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **93.2%** (41/44)
- 난이도별: compare 93.3% (15), lookup 93.1% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: exec_error 1, match 41, mismatch 2
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 4574, 중앙값 3132, 최대 14875
- 평균 토큰: 입력 1796, 출력 436 (추론 303)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 2811 | 72 |  |
| lookup-02 | match | 4640 | 214 |  |
| lookup-03 | match | 2000 | 131 |  |
| lookup-04 | match | 2797 | 138 |  |
| lookup-05 | match | 2905 | 208 |  |
| lookup-06 | match | 3655 | 212 |  |
| lookup-07 | match | 2343 | 160 |  |
| lookup-08 | mismatch | 2797 | 174 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-09 | match | 3609 | 164 |  |
| lookup-10 | match | 2844 | 188 |  |
| lookup-11 | match | 4968 | 484 |  |
| lookup-12 | match | 2531 | 176 |  |
| lookup-13 | match | 2452 | 219 |  |
| lookup-14 | match | 7702 | 883 |  |
| compare-01 | match | 8437 | 1064 |  |
| compare-02 | match | 2952 | 241 |  |
| compare-03 | match | 4858 | 474 |  |
| compare-04 | match | 6547 | 671 |  |
| compare-05 | match | 8844 | 827 |  |
| compare-06 | match | 11906 | 1540 |  |
| lookup-15 | match | 2437 | 146 |  |
| lookup-16 | match | 2656 | 167 |  |
| lookup-17 | match | 2672 | 267 |  |
| lookup-18 | match | 2922 | 225 |  |
| lookup-19 | match | 2218 | 132 |  |
| lookup-20 | match | 2452 | 178 |  |
| lookup-21 | match | 2344 | 185 |  |
| lookup-22 | exec_error | 7031 | 736 | 실행 시간이 5000ms 를 넘었습니다. 기간을 줄이거나 집계 테이블을 사용하세요. |
| lookup-23 | match | 6672 | 667 |  |
| lookup-24 | match | 2233 | 133 |  |
| lookup-25 | match | 1796 | 104 |  |
| lookup-26 | match | 2250 | 154 |  |
| lookup-27 | match | 2452 | 165 |  |
| lookup-28 | match | 3312 | 306 |  |
| lookup-29 | match | 3500 | 312 |  |
| compare-07 | match | 8860 | 1001 |  |
| compare-08 | match | 4203 | 412 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 6766 | 780 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 2781 | 188 |  |
| compare-11 | match | 6344 | 729 |  |
| compare-12 | mismatch | 9484 | 1092 | 행 수 불일치 (정답 1, 예측 2) |
| compare-13 | match | 4422 | 532 |  |
| compare-14 | match | 4969 | 553 |  |
| compare-15 | match | 14875 | 1767 |  |

## 실패 문항

### lookup-08 — mismatch

질문: 이번 달 결제 완료 건수는?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT COALESCE(SUM(event_count), 0) AS 결제_완료_건수
FROM agg_event_daily
WHERE summary_date >= date_trunc('month', current_date)::date
  AND summary_date < current_date
  AND event_name = 'is_payment';
```

### lookup-22 — exec_error

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 실행 시간이 5000ms 를 넘었습니다. 기간을 줄이거나 집계 테이블을 사용하세요.

```sql
WITH bounds AS (
    SELECT date_trunc('week', current_date)::date AS week_start
),
last_week_visitors AS (
    SELECT DISTINCT u.client_id
    FROM agg_daily_users AS u
    CROSS JOIN bounds AS b
    WHERE u.summary_date >= b.week_start - 7
      AND u.summary_date < b.week_start
),
classified_visitors AS (
    SELECT
        w.client_id,
        EXISTS (
            SELECT 1
            FROM agg_daily_users AS prior
            CROSS JOIN bounds AS b
            WHERE prior.client_id = w.client_id
              AND prior.summary_date < b.week_start - 7
        ) AS is_returning
    FROM last_week_visitors AS w
)
SELECT
    COUNT(*) FILTER (WHERE NOT is_returning) AS 신규_방문자_수,
    COUNT(*) FILTER (WHERE is_returning) AS 재방문자_수
FROM classified_visitors;
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
WITH periods AS (
    SELECT
        '지난달' AS period,
        (date_trunc('month', current_date) - interval '1 month')::date AS start_date,
        date_trunc('month', current_date)::date AS end_date
    UNION ALL
    SELECT
        '이번 달(오늘 제외)' AS period,
        date_trunc('month', current_date)::date AS start_date,
        current_date AS end_date
)
SELECT
    p.period AS 기간,
    COALESCE(SUM(a.page_views), 0)::numeric
        / NULLIF(p.end_date - p.start_date, 0) AS 일평균_페이지뷰
FROM periods p
LEFT JOIN agg_page_daily a
    ON a.summary_date >= p.start_date
   AND a.summary_date < p.end_date
GROUP BY p.period, p.start_date, p.end_date
ORDER BY p.start_date;
```

