# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-13T10:10:10+09:00 / local-single-prompt
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **88.6%** (39/44)
- 난이도별: compare 80.0% (15), lookup 93.1% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 39, mismatch 5
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 3문항
- 지연(ms): 평균 9245, 중앙값 7461, 최대 44046
- 평균 토큰: 입력 1861, 출력 700 (추론 0)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 44046 | 409 |  |
| lookup-02 | match | 4077 | 335 |  |
| lookup-03 | match | 3687 | 302 |  |
| lookup-04 | match | 4843 | 399 |  |
| lookup-05 | match | 5202 | 428 |  |
| lookup-06 | match | 5750 | 452 |  |
| lookup-07 | match | 5593 | 467 |  |
| lookup-08 | match | 3359 | 276 |  |
| lookup-09 | match | 3859 | 322 |  |
| lookup-10 | match | 7359 | 407 |  |
| lookup-11 | match | 9015 | 763 |  |
| lookup-12 | match | 7905 | 672 |  |
| lookup-13 | match | 7577 | 644 |  |
| lookup-14 | match | 7280 | 620 |  |
| compare-01 | match | 17281 | 1464 |  |
| compare-02 | match | 8047 | 676 |  |
| compare-03 | match | 9436 | 798 |  |
| compare-04 | match | 17922 | 1520 |  |
| compare-05 | match | 11014 | 939 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 14077 | 1196 |  |
| lookup-15 | match | 2858 | 239 |  |
| lookup-16 | match | 5780 | 486 |  |
| lookup-17 | match | 4797 | 403 |  |
| lookup-18 | match | 4625 | 389 |  |
| lookup-19 | match | 6469 | 546 |  |
| lookup-20 | match | 4858 | 409 |  |
| lookup-21 | match | 5609 | 476 |  |
| lookup-22 | mismatch | 25843 | 2202 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | mismatch | 7765 | 657 | 행 수 불일치 (정답 13, 예측 12) |
| lookup-24 | match | 5500 | 458 |  |
| lookup-25 | match | 3686 | 307 |  |
| lookup-26 | match | 11891 | 1004 |  |
| lookup-27 | match | 5311 | 441 |  |
| lookup-28 | match | 7500 | 634 |  |
| lookup-29 | match | 4125 | 342 |  |
| compare-07 | match | 9562 | 818 |  |
| compare-08 | match | 9281 | 782 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 16156 | 1364 |  |
| compare-10 | mismatch | 7937 | 664 | 행 수 불일치 (정답 7, 예측 0) |
| compare-11 | mismatch | 9000 | 754 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | match | 15875 | 1338 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 9734 | 829 |  |
| compare-14 | match | 7422 | 630 |  |
| compare-15 | mismatch | 17875 | 1523 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH all_visits AS (
  SELECT client_id, MIN(summary_date) AS first_visit_date
  FROM agg_daily_users
  GROUP BY client_id
),
last_week_clients AS (
  SELECT DISTINCT client_id
  FROM agg_daily_users
  WHERE summary_date >= date_trunc('week', current_date)::date - 7
    AND summary_date < date_trunc('week', current_date)::date
),
week_range AS (
  SELECT date_trunc('week', current_date)::date - 7 AS start_date,
         date_trunc('week', current_date)::date AS end_date
)
SELECT
  SUM(CASE WHEN lv.first_visit_date >= wr.start_date THEN 1 ELSE 0 END) AS new_visitors,
  SUM(CASE WHEN lv.first_visit_date < wr.start_date THEN 1 ELSE 0 END) AS returning_visitors
FROM last_week_clients c
JOIN all_visits lv ON lv.client_id = c.client_id
CROSS JOIN week_range wr;
```

### lookup-23 — mismatch

질문: 이번 달 일별 매출 추이를 보여줘

사유: 행 수 불일치 (정답 13, 예측 12)

```sql
SELECT
    summary_date,
    SUM(conversion_value_sum) AS total_sales
FROM
    agg_traffic_hourly
WHERE
    summary_date >= date_trunc('month', current_date)::date
    AND summary_date < current_date
GROUP BY
    summary_date
ORDER BY
    summary_date
LIMIT 1000;
```

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 행 수 불일치 (정답 7, 예측 0)

```sql
SELECT
    EXTRACT(isodow FROM summary_date)::int AS iso_weekday,
    SUM(sessions)::bigint AS email_sessions
FROM agg_traffic_hourly
WHERE summary_date >= current_date - 28
  AND summary_date < current_date
  AND traffic_medium = 'newsletter/email'
GROUP BY 1
ORDER BY 1;
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

```sql
SELECT
    date_trunc('day', timestamp)::date         AS summary_date,
    device_type                                 AS device_type,
    COUNT(*)                                    AS payment_count
FROM events
WHERE
    event_name = 'is_payment'
    AND timestamp >= current_date - 15
    AND timestamp < current_date - 13
GROUP BY summary_date, device_type
ORDER BY summary_date, device_type
LIMIT 1000;
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT
  traffic_source,
  SUM(sessions) AS total_sessions,
  SUM(conversions) AS total_conversions,
  ROUND(SUM(conversions)::numeric * 100 / NULLIF(SUM(sessions), 0), 2) AS conversion_rate_pct
FROM
  agg_traffic_hourly
WHERE
  summary_date >= date_trunc('week', current_date)::date - 7
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY
  traffic_source
HAVING
  SUM(sessions) >= 200
ORDER BY
  conversion_rate_pct DESC
LIMIT 3;
```

