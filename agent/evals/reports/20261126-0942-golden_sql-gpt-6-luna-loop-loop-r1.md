# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-26T09:42:24+09:00 / loop-r1
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **93.2%** (41/44)
- 난이도별: compare 86.7% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 41, mismatch 2, no_sql 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 2문항
- 지연(ms): 평균 6968, 중앙값 6265, 최대 12578
- 평균 토큰: 입력 5715, 출력 612 (추론 190)
- 실행한 SQL 중 하나라도 정답: 93.2%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력(추론) 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 11 | 2 | 2 | 5,778 | 1,028 (392) | 0.0 | 8,944 / 8,515 | 0.0% | 100.0% | 0 |
| lookup | 33 | 2.1 | 2.1 | 5,694 | 474 (122) | 0.0 | 6,309 / 5,875 | 0.0% | 97.0% | 0 |
| 전체 | 44 | 2.0 | 2.0 | 5,715 | 612 (190) | 0.0 | 6,968 / 6,265 | 0.0% | 97.7% | 0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 5250 | 215 |  |
| lookup-02 | match | 5952 | 422 |  |
| lookup-03 | match | 4907 | 342 |  |
| lookup-04 | match | 5422 | 352 |  |
| lookup-05 | match | 5875 | 451 |  |
| lookup-06 | match | 7219 | 739 |  |
| lookup-07 | match | 4797 | 301 |  |
| lookup-08 | match | 4625 | 238 |  |
| lookup-09 | match | 5733 | 325 |  |
| lookup-10 | match | 6686 | 608 |  |
| lookup-11 | match | 6688 | 609 |  |
| lookup-12 | match | 5405 | 440 |  |
| lookup-13 | match | 6188 | 511 |  |
| lookup-14 | match | 11500 | 1203 |  |
| compare-01 | match | 12578 | 1704 |  |
| compare-02 | match | 6405 | 585 |  |
| compare-03 | match | 7938 | 756 |  |
| compare-04 | match | 8625 | 776 |  |
| compare-05 | match | 8655 | 901 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 8078 | 881 |  |
| lookup-15 | match | 4796 | 210 |  |
| lookup-16 | match | 5313 | 367 |  |
| lookup-17 | match | 5500 | 387 |  |
| lookup-18 | match | 5765 | 363 |  |
| lookup-19 | match | 5109 | 332 |  |
| lookup-20 | match | 5671 | 334 |  |
| lookup-21 | match | 6171 | 532 |  |
| lookup-22 | no_sql | 11546 | 944 | 성공한 SQL 없음 (succeeded) |
| lookup-23 | match | 7766 | 632 |  |
| lookup-24 | match | 5233 | 343 |  |
| lookup-25 | match | 4983 | 293 |  |
| lookup-26 | match | 5921 | 373 |  |
| lookup-27 | match | 5452 | 340 |  |
| lookup-28 | match | 6016 | 451 |  |
| lookup-29 | match | 7015 | 533 |  |
| compare-07 | match | 8515 | 998 |  |
| compare-08 | match | 7390 | 732 |  |
| compare-09 | match | 8157 | 879 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 6796 | 483 |  |
| compare-11 | mismatch | 9438 | 971 | 행 수 불일치 (정답 3, 예측 6) |
| compare-12 | match | 9375 | 1225 |  |
| compare-13 | match | 7750 | 915 |  |
| compare-14 | match | 6342 | 440 |  |
| compare-15 | mismatch | 12047 | 1512 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-22 — no_sql

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 성공한 SQL 없음 (succeeded)

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 6)

```sql
WITH target_dates AS (SELECT (current_date - 15)::date AS summary_date UNION ALL SELECT (current_date - 14)::date), device_types AS (SELECT unnest(ARRAY['desktop','mobile','tablet']) AS device_type), counts AS (SELECT timestamp::date AS summary_date, device_type, count(*) AS payment_events FROM events WHERE timestamp >= (current_date - 15)::date AND timestamp < (current_date - 13)::date AND event_name = 'is_payment' GROUP BY timestamp::date, device_type) SELECT d.summary_date, t.device_type, COALESCE(c.payment_events, 0) AS payment_events FROM target_dates d CROSS JOIN device_types t LEFT JOIN counts c ON c.summary_date = d.summary_date AND c.device_type = t.device_type ORDER BY d.summary_date, t.device_type
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
  SELECT traffic_source, COUNT(DISTINCT session_id)::bigint AS paid_sessions
  FROM events
  WHERE timestamp >= date_trunc('week', current_date)::date - 7
    AND timestamp < date_trunc('week', current_date)::date
    AND event_name = 'is_payment'
  GROUP BY traffic_source
)
SELECT s.traffic_source,
       s.sessions,
       COALESCE(p.paid_sessions, 0) AS paid_sessions,
       ROUND(COALESCE(p.paid_sessions, 0) * 100.0 / NULLIF(s.sessions, 0), 2) AS paid_session_rate_pct
FROM source_sessions s
LEFT JOIN paid_sessions p USING (traffic_source)
WHERE s.sessions >= 200
ORDER BY paid_session_rate_pct DESC, s.traffic_source
LIMIT 3
```

