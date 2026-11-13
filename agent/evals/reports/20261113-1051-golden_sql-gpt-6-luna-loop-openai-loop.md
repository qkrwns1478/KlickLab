# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-13T10:51:45+09:00 / openai-loop
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **90.9%** (40/44)
- 난이도별: compare 80.0% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 40, mismatch 4
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 9984, 중앙값 8828, 최대 17952
- 평균 토큰: 입력 5259, 출력 602 (추론 0)
- 실행한 SQL 중 하나라도 정답: 90.9%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 17 | 2.1 | 2.1 | 5,465 | 845 | 0.0 | 12,668 / 13,358 | 0.0% | 94.1% | 0.1 |
| lookup | 27 | 2 | 2 | 5,130 | 449 | 0.0 | 8,294 / 7,875 | 0.0% | 100.0% | 0 |
| 전체 | 44 | 2.0 | 2.0 | 5,259 | 602 | 0.0 | 9,984 / 8,828 | 0.0% | 97.7% | 0.0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 7875 | 203 |  |
| lookup-02 | match | 7015 | 372 |  |
| lookup-03 | match | 7641 | 342 |  |
| lookup-04 | match | 6030 | 337 |  |
| lookup-05 | match | 6827 | 338 |  |
| lookup-06 | match | 10468 | 715 |  |
| lookup-07 | match | 6937 | 384 |  |
| lookup-08 | match | 6094 | 331 |  |
| lookup-09 | match | 4953 | 227 |  |
| lookup-10 | match | 7735 | 476 |  |
| lookup-11 | match | 10031 | 723 |  |
| lookup-12 | match | 8922 | 447 |  |
| lookup-13 | match | 8547 | 488 |  |
| lookup-14 | match | 10750 | 712 |  |
| compare-01 | mismatch | 13375 | 968 | 정답 3번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-02 | match | 8734 | 566 |  |
| compare-03 | match | 10358 | 665 |  |
| compare-04 | match | 14734 | 1084 |  |
| compare-05 | match | 12202 | 801 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 17906 | 1186 |  |
| lookup-15 | match | 7030 | 256 |  |
| lookup-16 | match | 7030 | 387 |  |
| lookup-17 | match | 7094 | 360 |  |
| lookup-18 | match | 7109 | 328 |  |
| lookup-19 | match | 5781 | 251 |  |
| lookup-20 | match | 8500 | 307 |  |
| lookup-21 | match | 7250 | 468 |  |
| lookup-22 | mismatch | 9000 | 629 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 14155 | 845 |  |
| lookup-24 | match | 7983 | 324 |  |
| lookup-25 | match | 11422 | 293 |  |
| lookup-26 | match | 6094 | 304 |  |
| lookup-27 | match | 7062 | 351 |  |
| lookup-28 | match | 9891 | 480 |  |
| lookup-29 | match | 10594 | 622 |  |
| compare-07 | match | 13750 | 1021 |  |
| compare-08 | match | 9453 | 696 |  |
| compare-09 | match | 17343 | 1212 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 8266 | 587 |  |
| compare-11 | mismatch | 13358 | 842 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | mismatch | 17734 | 1189 | 행 수 불일치 (정답 1, 예측 2) |
| compare-13 | match | 13031 | 914 |  |
| compare-14 | match | 15280 | 1036 |  |
| compare-15 | match | 17952 | 1414 |  |

## 실패 문항

### compare-01 — mismatch

질문: 지난주 대비 이번 주 유입 소스(traffic_source)별 세션 수를 비교해줘

사유: 정답 3번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT traffic_source,
       SUM(sessions) FILTER (WHERE summary_date >= date_trunc('week', current_date)::date - 7 AND summary_date < date_trunc('week', current_date)::date) AS last_week_sessions,
       SUM(sessions) FILTER (WHERE summary_date >= date_trunc('week', current_date)::date AND summary_date < current_date) AS this_week_sessions,
       SUM(sessions) FILTER (WHERE summary_date >= date_trunc('week', current_date)::date AND summary_date < current_date)
         - SUM(sessions) FILTER (WHERE summary_date >= date_trunc('week', current_date)::date - 7 AND summary_date < date_trunc('week', current_date)::date) AS change_sessions
FROM agg_traffic_hourly
WHERE (summary_date >= date_trunc('week', current_date)::date - 7 AND summary_date < date_trunc('week', current_date)::date)
   OR (summary_date >= date_trunc('week', current_date)::date AND summary_date < current_date)
GROUP BY traffic_source
ORDER BY this_week_sessions DESC NULLS LAST, last_week_sessions DESC NULLS LAST
```

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH week_users AS (SELECT DISTINCT client_id FROM agg_daily_users WHERE summary_date >= date_trunc('week', current_date)::date - 7 AND summary_date < date_trunc('week', current_date)::date), prior_users AS (SELECT DISTINCT client_id FROM agg_daily_users WHERE summary_date < date_trunc('week', current_date)::date - 7) SELECT COUNT(*) FILTER (WHERE p.client_id IS NULL) AS new_visitors, COUNT(*) FILTER (WHERE p.client_id IS NOT NULL) AS returning_visitors, COUNT(*) AS total_unique_visitors FROM week_users w LEFT JOIN prior_users p USING (client_id)
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

```sql
SELECT timestamp::date AS event_date, device_type, COUNT(*) AS payment_complete_count FROM events WHERE timestamp >= current_date - INTERVAL '15 days' AND timestamp < current_date - INTERVAL '13 days' AND event_name = 'is_payment' GROUP BY timestamp::date, device_type ORDER BY event_date, device_type
```

### compare-12 — mismatch

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
WITH periods AS (
  SELECT '지난달'::text AS period,
         (date_trunc('month', current_date) - interval '1 month')::date AS start_date,
         date_trunc('month', current_date)::date AS end_date
  UNION ALL
  SELECT '이번 달(오늘 제외)',
         date_trunc('month', current_date)::date,
         current_date
)
SELECT p.period,
       COALESCE(SUM(a.page_views), 0) AS total_pageviews,
       (p.end_date - p.start_date) AS days_in_period,
       ROUND(COALESCE(SUM(a.page_views), 0)::numeric / NULLIF(p.end_date - p.start_date, 0), 2) AS avg_daily_pageviews
FROM periods p
LEFT JOIN agg_page_daily a
  ON a.summary_date >= p.start_date AND a.summary_date < p.end_date
GROUP BY p.period, p.start_date, p.end_date
ORDER BY p.start_date
```

