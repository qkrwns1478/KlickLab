# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-26T09:56:09+09:00 / local-loop
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **84.1%** (37/44)
- 난이도별: compare 73.3% (15), lookup 89.7% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 37, mismatch 6, no_sql 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 23171, 중앙값 20054, 최대 61313
- 평균 토큰: 입력 10636, 출력 1922 (추론 0)
- 실행한 SQL 중 하나라도 정답: 84.1%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력(추론) 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 13 | 3.8 | 3.9 | 11,420 | 1,939 (0) | 0.0 | 22,771 / 20,030 | 0.0% | 84.6% | 0.2 |
| lookup | 31 | 3.5 | 3.7 | 10,307 | 1,915 (0) | 0.0 | 23,339 / 20,077 | 3.2% | 93.5% | 0.0 |
| 전체 | 44 | 3.5 | 3.8 | 10,636 | 1,922 (0) | 0.0 | 23,171 / 20,054 | 2.3% | 90.9% | 0.1 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 14061 | 1062 |  |
| lookup-02 | match | 22827 | 1853 |  |
| lookup-03 | match | 48875 | 3989 |  |
| lookup-04 | match | 7858 | 622 |  |
| lookup-05 | match | 22719 | 1885 |  |
| lookup-06 | match | 25953 | 2121 |  |
| lookup-07 | match | 10109 | 815 |  |
| lookup-08 | match | 16452 | 1345 |  |
| lookup-09 | match | 14046 | 1130 |  |
| lookup-10 | match | 29750 | 2403 |  |
| lookup-11 | match | 61313 | 4991 |  |
| lookup-12 | match | 11453 | 896 |  |
| lookup-13 | match | 36453 | 2956 |  |
| lookup-14 | match | 14907 | 1209 |  |
| compare-01 | match | 34188 | 2765 |  |
| compare-02 | match | 18171 | 1554 |  |
| compare-03 | match | 14094 | 1203 |  |
| compare-04 | no_sql | 35327 | 3031 | 성공한 SQL 없음 (budget_exhausted) |
| compare-05 | mismatch | 18500 | 1611 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-06 | match | 23390 | 2031 |  |
| lookup-15 | match | 18422 | 1595 |  |
| lookup-16 | match | 10592 | 888 |  |
| lookup-17 | match | 8890 | 750 |  |
| lookup-18 | match | 15188 | 1308 |  |
| lookup-19 | match | 21139 | 1822 |  |
| lookup-20 | mismatch | 20733 | 1783 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-21 | match | 23891 | 2072 |  |
| lookup-22 | mismatch | 38983 | 3415 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 45469 | 2905 |  |
| lookup-24 | match | 30235 | 2605 |  |
| lookup-25 | match | 13483 | 1144 |  |
| lookup-26 | mismatch | 20077 | 1730 | 행 수 불일치 (정답 2, 예측 0) |
| lookup-27 | match | 27875 | 2426 |  |
| lookup-28 | match | 17891 | 1196 |  |
| lookup-29 | match | 25922 | 2234 |  |
| compare-07 | match | 17561 | 1521 |  |
| compare-08 | match | 13532 | 1155 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 38561 | 3198 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 32046 | 2760 |  |
| compare-11 | mismatch | 20030 | 1753 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | match | 27516 | 2426 |  |
| compare-13 | match | 18188 | 1580 |  |
| compare-14 | match | 19532 | 1692 |  |
| compare-15 | mismatch | 13328 | 1150 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### compare-04 — no_sql

질문: 최근 7일 기기 유형별 결제 전환율(%)을 알려줘. 결제(is_payment) 이벤트가 있었던 세션의 비율로 계산해줘

사유: 성공한 SQL 없음 (budget_exhausted)

### compare-05 — mismatch

질문: 최근 7일과 그 전 7일의 일평균 순 방문자 수를 비교해줘

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH recent_counts AS (
  SELECT COUNT(DISTINCT client_id) AS visits
  FROM agg_daily_users
  WHERE summary_date >= current_date - 7 AND summary_date < current_date
),
prev_counts AS (
  SELECT COUNT(DISTINCT client_id) AS visits
  FROM agg_daily_users
  WHERE summary_date >= current_date - 14 AND summary_date < current_date - 7
),
recent_avg AS (
  SELECT ROUND(AVG(visits),2) AS avg_visits
  FROM recent_counts
),
prev_avg AS (
  SELECT ROUND(AVG(visits),2) AS avg_visits
  FROM prev_counts
)
SELECT
  rec.avg_visits AS recent_avg,
  pre.avg_visits AS prev_avg,
  ROUND((rec.avg_visits - pre.avg_visits) / NULLIF(pre.avg_visits,0) * 100.0, 2) AS percent_change
FROM recent_avg rec
CROSS JOIN prev_avg pre;
```

### lookup-20 — mismatch

질문: 최근 7일 /products 페이지의 평균 체류 시간(초)은?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT SUM(time_on_page_sum) AS total_time, SUM(page_views) AS total_views
FROM agg_page_daily
WHERE summary_date >= current_date - 7
  AND summary_date < current_date
  AND page_path = '/products';
```

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH first_vis AS (
  SELECT client_id, MIN(timestamp)::date AS first_date
  FROM events
  WHERE timestamp < current_date
  GROUP BY client_id
), last_week_vis AS (
  SELECT DISTINCT client_id
  FROM events
  WHERE timestamp >= date_trunc('week', current_date)::date - INTERVAL '7 days'
    AND timestamp < date_trunc('week', current_date)::date
)
SELECT
  (SELECT COUNT(*) FROM first_vis fv
   WHERE fv.first_date >= date_trunc('week', current_date)::date - INTERVAL '7 days'
     AND fv.first_date < date_trunc('week', current_date)::date) AS new_visitors,
  (SELECT COUNT(*) FROM last_week_vis lw
   JOIN first_vis fv ON lw.client_id = fv.client_id
   WHERE fv.first_date < date_trunc('week', current_date)::date) AS returning_visitors;
```

### lookup-26 — mismatch

질문: 최근 14일 카카오(kakao) 유입의 매체별 세션 수는?

사유: 행 수 불일치 (정답 2, 예측 0)

```sql
SELECT traffic_source, SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE summary_date >= current_date - 14 AND summary_date < current_date
  AND traffic_source LIKE 'kakao/%'
GROUP BY traffic_source
ORDER BY sessions DESC;
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

```sql
SELECT DATE(timestamp) AS payment_date, device_type, COUNT(*) AS payment_count FROM events WHERE event_name='is_payment' AND timestamp >= '2026-11-11' AND timestamp < '2026-11-13' GROUP BY payment_date, device_type ORDER BY payment_date, device_type;
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT
  traffic_source,
  SUM(sessions) AS total_sessions,
  SUM(conversions) AS total_conversions,
  SUM(conversions)::numeric * 100.0 / NULLIF(SUM(sessions), 0) AS conversion_rate
FROM agg_traffic_hourly
WHERE summary_date >= DATE_TRUNC('week', CURRENT_DATE)::date - INTERVAL '7 days'
  AND summary_date < DATE_TRUNC('week', CURRENT_DATE)::date
GROUP BY traffic_source
HAVING SUM(sessions) >= 200
ORDER BY conversion_rate DESC
LIMIT 3;
```

