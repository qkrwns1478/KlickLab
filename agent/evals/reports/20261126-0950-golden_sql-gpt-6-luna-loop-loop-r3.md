# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-26T09:50:28+09:00 / loop-r3
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 93.3% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 42, mismatch 1, no_sql 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 4문항
- 지연(ms): 평균 6971, 중앙값 6250, 최대 15094
- 평균 토큰: 입력 5769, 출력 598 (추론 186)
- 실행한 SQL 중 하나라도 정답: 95.5%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력(추론) 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 13 | 2.1 | 2.1 | 5,962 | 959 (362) | 0.0 | 8,782 / 8,280 | 0.0% | 100.0% | 0 |
| lookup | 31 | 2.1 | 2.1 | 5,688 | 447 (111) | 0.0 | 6,212 / 5,703 | 0.0% | 96.8% | 0 |
| 전체 | 44 | 2.1 | 2.1 | 5,769 | 598 (186) | 0.0 | 6,971 / 6,250 | 0.0% | 97.7% | 0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 4719 | 195 |  |
| lookup-02 | match | 6842 | 514 |  |
| lookup-03 | match | 5280 | 372 |  |
| lookup-04 | match | 5561 | 394 |  |
| lookup-05 | match | 5109 | 355 |  |
| lookup-06 | match | 6157 | 500 |  |
| lookup-07 | match | 5046 | 311 |  |
| lookup-08 | match | 8484 | 299 |  |
| lookup-09 | match | 5171 | 304 |  |
| lookup-10 | match | 5984 | 441 |  |
| lookup-11 | match | 8750 | 912 |  |
| lookup-12 | match | 5842 | 505 |  |
| lookup-13 | match | 6703 | 594 |  |
| lookup-14 | match | 7594 | 581 |  |
| compare-01 | match | 10094 | 1269 |  |
| compare-02 | match | 7234 | 685 |  |
| compare-03 | match | 7608 | 650 |  |
| compare-04 | match | 8625 | 858 |  |
| compare-05 | match | 6859 | 675 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 8280 | 921 |  |
| lookup-15 | match | 4640 | 264 |  |
| lookup-16 | match | 5703 | 370 |  |
| lookup-17 | match | 5844 | 329 |  |
| lookup-18 | match | 5515 | 399 |  |
| lookup-19 | match | 4655 | 303 |  |
| lookup-20 | match | 6155 | 339 |  |
| lookup-21 | match | 6375 | 539 |  |
| lookup-22 | no_sql | 11921 | 858 | 성공한 SQL 없음 (succeeded) |
| lookup-23 | match | 8140 | 697 |  |
| lookup-24 | match | 4984 | 287 |  |
| lookup-25 | match | 4953 | 301 |  |
| lookup-26 | match | 5328 | 366 |  |
| lookup-27 | match | 5233 | 367 |  |
| lookup-28 | match | 5094 | 328 |  |
| lookup-29 | match | 4938 | 358 |  |
| compare-07 | match | 7469 | 887 |  |
| compare-08 | match | 6344 | 629 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 7327 | 775 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 5984 | 511 |  |
| compare-11 | mismatch | 10936 | 1205 | 행 수 불일치 (정답 3, 예측 6) |
| compare-12 | match | 8797 | 1056 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 9328 | 907 |  |
| compare-14 | match | 10030 | 1000 |  |
| compare-15 | match | 15094 | 1914 |  |

## 실패 문항

### lookup-22 — no_sql

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 성공한 SQL 없음 (succeeded)

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 6)

```sql
WITH dates(event_date) AS (VALUES (current_date - 15), (current_date - 14)), device_types(device_type) AS (VALUES ('desktop'::text), ('mobile'::text), ('tablet'::text)), counts AS (SELECT timestamp::date AS event_date, device_type, COUNT(*) AS event_count FROM events WHERE timestamp >= current_date - 15 AND timestamp < current_date - 13 AND event_name = 'is_payment' GROUP BY timestamp::date, device_type) SELECT d.event_date, t.device_type, COALESCE(c.event_count, 0) AS payment_completion_events FROM dates d CROSS JOIN device_types t LEFT JOIN counts c ON c.event_date = d.event_date AND c.device_type = t.device_type ORDER BY d.event_date, t.device_type
```

