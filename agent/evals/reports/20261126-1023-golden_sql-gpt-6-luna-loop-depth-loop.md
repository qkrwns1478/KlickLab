# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-26T10:23:14+09:00 / depth-loop
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 93.3% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 42, mismatch 2
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 3문항
- 지연(ms): 평균 7453, 중앙값 6876, 최대 26907
- 평균 토큰: 입력 5745, 출력 620 (추론 203)
- 실행한 SQL 중 하나라도 정답: 95.5%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력(추론) 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 13 | 2.2 | 2.2 | 6,301 | 1,033 (416) | 0.0 | 9,632 / 8,282 | 0.0% | 100.0% | 0 |
| lookup | 31 | 2 | 2 | 5,511 | 447 (113) | 0.0 | 6,539 / 6,578 | 0.0% | 100.0% | 0 |
| 전체 | 44 | 2.0 | 2.0 | 5,744 | 620 (202) | 0.0 | 7,453 / 6,876 | 0.0% | 100.0% | 0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 6672 | 215 |  |
| lookup-02 | match | 6563 | 462 |  |
| lookup-03 | match | 6967 | 413 |  |
| lookup-04 | match | 9578 | 366 |  |
| lookup-05 | match | 6109 | 389 |  |
| lookup-06 | match | 6921 | 529 |  |
| lookup-07 | match | 4530 | 275 |  |
| lookup-08 | match | 5219 | 283 |  |
| lookup-09 | match | 4342 | 235 |  |
| lookup-10 | match | 6844 | 562 |  |
| lookup-11 | match | 8375 | 828 |  |
| lookup-12 | match | 7077 | 600 |  |
| lookup-13 | match | 6907 | 583 |  |
| lookup-14 | match | 7265 | 616 |  |
| compare-01 | match | 26907 | 3617 |  |
| compare-02 | match | 7561 | 613 |  |
| compare-03 | match | 7344 | 682 |  |
| compare-04 | match | 9827 | 961 |  |
| compare-05 | match | 9125 | 862 |  |
| compare-06 | match | 8561 | 958 |  |
| lookup-15 | match | 4188 | 216 |  |
| lookup-16 | match | 5296 | 370 |  |
| lookup-17 | match | 6000 | 351 |  |
| lookup-18 | match | 5655 | 383 |  |
| lookup-19 | match | 5157 | 283 |  |
| lookup-20 | match | 5265 | 309 |  |
| lookup-21 | match | 6530 | 584 |  |
| lookup-22 | mismatch | 8594 | 699 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 8780 | 774 |  |
| lookup-24 | match | 5046 | 296 |  |
| lookup-25 | match | 6000 | 288 |  |
| lookup-26 | match | 5530 | 378 |  |
| lookup-27 | match | 8078 | 341 |  |
| lookup-28 | match | 6733 | 448 |  |
| lookup-29 | match | 6578 | 542 |  |
| compare-07 | match | 7530 | 832 |  |
| compare-08 | match | 6563 | 547 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 7953 | 805 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 6655 | 437 |  |
| compare-11 | mismatch | 8782 | 788 | 행 수 불일치 (정답 3, 예측 5) |
| compare-12 | match | 8282 | 928 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 9092 | 1050 |  |
| compare-14 | match | 5516 | 326 |  |
| compare-15 | match | 11421 | 1265 |  |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH params AS (SELECT date_trunc('week', current_date)::date - 7 AS week_start, date_trunc('week', current_date)::date AS week_end), active_week AS (SELECT DISTINCT d.client_id FROM agg_daily_users d CROSS JOIN params p WHERE d.summary_date >= p.week_start AND d.summary_date < p.week_end), prior AS (SELECT DISTINCT d.client_id FROM agg_daily_users d CROSS JOIN params p WHERE d.summary_date < p.week_start) SELECT COUNT(*) FILTER (WHERE pr.client_id IS NULL) AS new_visitors, COUNT(*) FILTER (WHERE pr.client_id IS NOT NULL) AS returning_visitors, COUNT(*) AS total_unique_visitors FROM active_week aw LEFT JOIN prior pr ON pr.client_id = aw.client_id
```

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 5)

```sql
SELECT timestamp::date AS event_date, device_type, count(*) AS payment_completions FROM events WHERE timestamp >= current_date - 15 AND timestamp < current_date - 13 AND event_name = 'is_payment' GROUP BY timestamp::date, device_type ORDER BY event_date, device_type
```

