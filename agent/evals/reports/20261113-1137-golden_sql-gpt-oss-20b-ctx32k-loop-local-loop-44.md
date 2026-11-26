# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-13T11:37:14+09:00 / local-loop-44
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **79.1%** (34/43) — 공급자 오류로 평가 못 한 문항 1/44
- 난이도별: compare 53.3% (15), lookup 92.9% (28) / 스키마 요약 밖 지식 75.0% (4)
- 상태: llm_error 1, match 34, mismatch 8, no_sql 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 19820, 중앙값 17390, 최대 44671
- 평균 토큰: 입력 10325, 출력 1664 (추론 0)
- 실행한 SQL 중 하나라도 정답: 77.3%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 11 | 3.7 | 4.2 | 11,495 | 2,067 | 0.0 | 24,585 / 24,780 | 0.0% | 100.0% | 0 |
| lookup | 33 | 3.5 | 3.8 | 9,935 | 1,530 | 0.0 | 18,737 / 16,625 | 3.0% | 90.9% | 0.1 |
| 전체 | 44 | 3.6 | 3.9 | 10,325 | 1,664 | 0.0 | 20,199 / 17,773 | 2.3% | 93.2% | 0.0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 12140 | 482 |  |
| lookup-02 | match | 14344 | 1201 |  |
| lookup-03 | match | 12265 | 1029 |  |
| lookup-04 | match | 7655 | 633 |  |
| lookup-05 | match | 18875 | 1431 |  |
| lookup-06 | match | 11437 | 972 |  |
| lookup-07 | match | 17359 | 1505 |  |
| lookup-08 | match | 16625 | 1433 |  |
| lookup-09 | mismatch | 11187 | 958 | 행 수 불일치 (정답 3, 예측 13) |
| lookup-10 | match | 26281 | 2258 |  |
| lookup-11 | match | 21469 | 1838 |  |
| lookup-12 | match | 15156 | 1302 |  |
| lookup-13 | match | 19155 | 1643 |  |
| lookup-14 | match | 30641 | 2659 |  |
| compare-01 | match | 9077 | 768 |  |
| compare-02 | match | 33547 | 2690 |  |
| compare-03 | no_sql | 13250 | 1120 | 성공한 SQL 없음 (succeeded) |
| compare-04 | match | 22844 | 1933 |  |
| compare-05 | match | 16530 | 1438 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 28016 | 2411 |  |
| lookup-15 | match | 8514 | 709 |  |
| lookup-16 | match | 19188 | 1652 |  |
| lookup-17 | match | 9218 | 761 |  |
| lookup-18 | match | 12625 | 1058 |  |
| lookup-19 | match | 17390 | 1509 |  |
| lookup-20 | match | 16437 | 1421 |  |
| lookup-21 | match | 16937 | 1446 |  |
| lookup-22 | mismatch | 43077 | 3759 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | llm_error | 36484 | 1404 | LLM 서비스에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요. |
| lookup-24 | match | 13703 | 1167 |  |
| lookup-25 | match | 8500 | 709 |  |
| lookup-26 | match | 44671 | 3904 |  |
| lookup-27 | match | 14469 | 1244 |  |
| lookup-28 | match | 10438 | 893 |  |
| lookup-29 | match | 24139 | 2094 |  |
| compare-07 | match | 35687 | 2734 |  |
| compare-08 | match | 25296 | 2188 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | mismatch | 18156 | 1542 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-10 | mismatch | 37827 | 3183 | 행 수 불일치 (정답 7, 예측 0) |
| compare-11 | mismatch | 24578 | 2098 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | mismatch | 30625 | 2651 | 행 수 불일치 (정답 1, 예측 2) |
| compare-13 | mismatch | 24780 | 2120 | 행 수 불일치 (정답 9, 예측 18) |
| compare-14 | match | 18875 | 1631 |  |
| compare-15 | mismatch | 19280 | 1646 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-09 — mismatch

질문: 어제 성별 방문자 수는?

사유: 행 수 불일치 (정답 3, 예측 13)

```sql
SELECT gender, users FROM agg_user_session_daily WHERE summary_date = current_date - 1;
```

### compare-03 — no_sql

질문: 최근 28일 동안 요일별(ISO 요일 번호, 월=1) 하루 평균 세션 수는?

사유: 성공한 SQL 없음 (succeeded)

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH last_week_vis AS (
  SELECT DISTINCT client_id
  FROM agg_daily_users
  WHERE summary_date >= date_trunc('week', current_date)::date - INTERVAL '7 days'
    AND summary_date < date_trunc('week', current_date)::date
),
vis_first_dates AS (
  SELECT lv.client_id, MIN(au.summary_date) AS first_date
  FROM last_week_vis lv
  JOIN agg_daily_users au ON lv.client_id = au.client_id
  GROUP BY lv.client_id
)
SELECT
  SUM(CASE WHEN first_date >= date_trunc('week', current_date)::date - INTERVAL '7 days'
           AND first_date < date_trunc('week', current_date)::date THEN 1 ELSE 0 END) AS new_visitors,
  SUM(CASE WHEN first_date < date_trunc('week', current_date)::date - INTERVAL '7 days' THEN 1 ELSE 0 END) AS returning_visitors
FROM vis_first_dates;
```

### lookup-23 — llm_error

질문: 이번 달 일별 매출 추이를 보여줘

사유: LLM 서비스에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.

### compare-09 — mismatch

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH daily_sessions AS (
    SELECT summary_date, SUM(sessions) AS sessions
    FROM agg_traffic_hourly
    WHERE summary_date >= current_date - 28
      AND summary_date <= current_date
    GROUP BY summary_date
)
SELECT
    SUM(CASE WHEN EXTRACT(dow FROM summary_date) IN (0,6) THEN sessions END)::numeric / NULLIF(SUM(CASE WHEN EXTRACT(dow FROM summary_date) IN (0,6) THEN 1 END),0) AS weekend_avg,
    SUM(CASE WHEN EXTRACT(dow FROM summary_date) BETWEEN 1 AND 5 THEN sessions END)::numeric / NULLIF(SUM(CASE WHEN EXTRACT(dow FROM summary_date) BETWEEN 1 AND 5 THEN 1 END),0) AS weekday_avg
FROM daily_sessions;
```

### compare-10 — mismatch

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: 행 수 불일치 (정답 7, 예측 0)

```sql
SELECT date_part('isodow', summary_date)::int AS iso_dow, SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE traffic_source='newsletter/email' AND summary_date >= current_date - 28 AND summary_date < current_date
GROUP BY iso_dow
ORDER BY iso_dow;
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

```sql
SELECT
  CASE
    WHEN ts >= (current_date - 15) AND ts < (current_date - 14) THEN '15일 전'
    WHEN ts >= (current_date - 14) AND ts < (current_date - 13) THEN '14일 전'
  END AS day_ref,
  device_type,
  COUNT(*) AS conversions
FROM (
  SELECT event_name, timestamp AS ts, device_type
  FROM events
  WHERE event_name = 'is_payment'
    AND timestamp >= (current_date - 15) AND timestamp < (current_date - 13)
) e
GROUP BY day_ref, device_type
ORDER BY day_ref, device_type;
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
WITH monthly AS (
  SELECT
    CASE 
        WHEN summary_date >= date_trunc('month', current_date - interval '1 month')::date
           AND summary_date < date_trunc('month', current_date)::date
        THEN 'last_month'
        WHEN summary_date >= date_trunc('month', current_date)::date
           AND summary_date < current_date
        THEN 'this_month'
    END AS period,
    SUM(page_views) AS total_page_views,
    COUNT(DISTINCT summary_date) AS days
  FROM agg_page_daily
  WHERE (summary_date >= date_trunc('month', current_date - interval '1 month')::date
          AND summary_date < date_trunc('month', current_date)::date)
     OR (summary_date >= date_trunc('month', current_date)::date
          AND summary_date < current_date)
  GROUP BY period
)
SELECT period,
       total_page_views,
       days,
       total_page_views::numeric / NULLIF(days,0) AS avg_daily_page_views
FROM monthly;
```

### compare-13 — mismatch

질문: 최근 7일과 그 전 7일의 유입 소스(traffic_source)별 전환 수를 비교해줘

사유: 행 수 불일치 (정답 9, 예측 18)

```sql
SELECT period, traffic_source, SUM(conversions) AS conversions FROM (
  SELECT 'recent' AS period, traffic_source, conversions FROM agg_traffic_hourly
  WHERE summary_date >= current_date - 7 AND summary_date < current_date
  UNION ALL
  SELECT 'previous' AS period, traffic_source, conversions FROM agg_traffic_hourly
  WHERE summary_date >= current_date - 14 AND summary_date < current_date - 7
) sub
GROUP BY period, traffic_source
ORDER BY period, traffic_source;
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT traffic_source, sum(sessions) AS total_sessions, sum(conversions) AS total_conversions, sum(conversions)::numeric*100.0 / NULLIF(sum(sessions),0) AS conversion_rate
FROM agg_traffic_hourly
WHERE summary_date >= date_trunc('week', current_date)::date - 7
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY traffic_source
HAVING sum(sessions) >= 200
ORDER BY conversion_rate DESC
LIMIT 3;
```

