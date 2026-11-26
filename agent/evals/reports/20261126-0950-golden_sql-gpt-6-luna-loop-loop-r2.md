# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-26T09:50:28+09:00 / loop-r2
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 93.3% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 42, mismatch 2
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 4문항
- 지연(ms): 평균 6914, 중앙값 6312, 최대 14625
- 평균 토큰: 입력 5723, 출력 616 (추론 195)
- 실행한 SQL 중 하나라도 정답: 95.5%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력(추론) 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 14 | 2.1 | 2.1 | 6,178 | 1,018 (418) | 0.0 | 8,925 / 8,140 | 0.0% | 85.7% | 0.1 |
| lookup | 30 | 2 | 2 | 5,510 | 428 (90) | 0.0 | 5,976 / 5,593 | 0.0% | 100.0% | 0 |
| 전체 | 44 | 2.0 | 2.0 | 5,722 | 616 (195) | 0.0 | 6,914 / 6,312 | 0.0% | 95.5% | 0.0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 6186 | 204 |  |
| lookup-02 | match | 5671 | 343 |  |
| lookup-03 | match | 5375 | 335 |  |
| lookup-04 | match | 5703 | 380 |  |
| lookup-05 | match | 5234 | 328 |  |
| lookup-06 | match | 5797 | 450 |  |
| lookup-07 | match | 5140 | 305 |  |
| lookup-08 | match | 5311 | 226 |  |
| lookup-09 | match | 4219 | 243 |  |
| lookup-10 | match | 6828 | 721 |  |
| lookup-11 | match | 8515 | 832 |  |
| lookup-12 | match | 5484 | 455 |  |
| lookup-13 | match | 6061 | 593 |  |
| lookup-14 | match | 6890 | 481 |  |
| compare-01 | match | 9186 | 1140 |  |
| compare-02 | match | 7061 | 689 |  |
| compare-03 | match | 7047 | 697 |  |
| compare-04 | match | 9875 | 1027 |  |
| compare-05 | match | 8155 | 950 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 10969 | 1187 |  |
| lookup-15 | match | 4686 | 258 |  |
| lookup-16 | match | 6952 | 368 |  |
| lookup-17 | match | 5672 | 391 |  |
| lookup-18 | match | 5125 | 357 |  |
| lookup-19 | match | 5515 | 260 |  |
| lookup-20 | match | 5936 | 391 |  |
| lookup-21 | match | 6453 | 527 |  |
| lookup-22 | mismatch | 14625 | 1951 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 8219 | 798 |  |
| lookup-24 | match | 4969 | 305 |  |
| lookup-25 | match | 4969 | 296 |  |
| lookup-26 | match | 5452 | 312 |  |
| lookup-27 | match | 4842 | 352 |  |
| lookup-28 | match | 5438 | 417 |  |
| lookup-29 | match | 5327 | 385 |  |
| compare-07 | match | 7858 | 913 |  |
| compare-08 | match | 6500 | 582 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 8125 | 781 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 6438 | 402 |  |
| compare-11 | match | 11155 | 1408 |  |
| compare-12 | match | 7890 | 881 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 9922 | 1314 |  |
| compare-14 | match | 6844 | 573 |  |
| compare-15 | mismatch | 10594 | 1297 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH bounds AS (
  SELECT (date_trunc('week', current_date)::date - 7) AS week_start,
         date_trunc('week', current_date)::date AS week_end
), first_seen AS (
  SELECT client_id, MIN(summary_date) AS first_date
  FROM agg_daily_users
  WHERE client_id IS NOT NULL
  GROUP BY client_id
), week_visitors AS (
  SELECT DISTINCT d.client_id
  FROM agg_daily_users d CROSS JOIN bounds b
  WHERE d.summary_date >= b.week_start AND d.summary_date < b.week_end
    AND d.client_id IS NOT NULL
)
SELECT b.week_start, b.week_end - 1 AS week_last_day,
       COUNT(*) FILTER (WHERE f.first_date >= b.week_start AND f.first_date < b.week_end) AS new_visitors,
       COUNT(*) FILTER (WHERE f.first_date < b.week_start) AS returning_visitors,
       COUNT(*) AS total_visitors
FROM week_visitors w
CROSS JOIN bounds b
LEFT JOIN first_seen f ON f.client_id = w.client_id
GROUP BY b.week_start, b.week_end
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH source_sessions AS (
  SELECT traffic_source, SUM(sessions)::bigint AS sessions
  FROM agg_traffic_hourly
  WHERE summary_date >= date_trunc('week', current_date)::date - 7
    AND summary_date < date_trunc('week', current_date)::date
  GROUP BY traffic_source
), paid_sessions AS (
  SELECT traffic_source, COUNT(DISTINCT session_id)::bigint AS paying_sessions
  FROM events
  WHERE timestamp >= date_trunc('week', current_date)::date - 7
    AND timestamp < date_trunc('week', current_date)::date
    AND event_name = 'is_payment'
  GROUP BY traffic_source
)
SELECT s.traffic_source, s.sessions, COALESCE(p.paying_sessions, 0) AS paying_sessions,
       ROUND(COALESCE(p.paying_sessions, 0) * 100.0 / NULLIF(s.sessions, 0), 2) AS paying_session_rate_pct
FROM source_sessions s
LEFT JOIN paid_sessions p USING (traffic_source)
WHERE s.sessions >= 200
ORDER BY paying_session_rate_pct DESC, s.traffic_source
LIMIT 3
```

