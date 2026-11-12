# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-12T14:06:05+09:00 / phase0-local
- 모델: groq / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **95.0%** (19/20)
- 난이도별: compare 100.0% (6), lookup 92.9% (14) / 스키마 요약 밖 지식 - (0)
- 상태: match 19, mismatch 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 23712, 중앙값 19445, 최대 59077
- 평균 토큰: 입력 1861, 출력 1964 (추론 0)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 18406 | 1508 |  |
| lookup-02 | match | 18375 | 1537 |  |
| lookup-03 | match | 10078 | 853 |  |
| lookup-04 | match | 16562 | 1401 |  |
| lookup-05 | match | 13093 | 1107 |  |
| lookup-06 | match | 12156 | 863 |  |
| lookup-07 | match | 23469 | 1986 |  |
| lookup-08 | mismatch | 41375 | 3464 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-09 | match | 31625 | 2665 |  |
| lookup-10 | match | 17312 | 1449 |  |
| lookup-11 | match | 20484 | 1730 |  |
| lookup-12 | match | 17468 | 1449 |  |
| lookup-13 | match | 15358 | 1294 |  |
| lookup-14 | match | 11922 | 1010 |  |
| compare-01 | match | 22515 | 1888 |  |
| compare-02 | match | 23906 | 1847 |  |
| compare-03 | match | 39811 | 3336 |  |
| compare-04 | match | 25468 | 1929 |  |
| compare-05 | match | 35780 | 3015 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 59077 | 4940 |  |

## 실패 문항

### lookup-08 — mismatch

질문: 이번 달 결제 완료 건수는?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT COALESCE(SUM(conversions), 0) AS payment_completions
FROM agg_traffic_hourly
WHERE summary_date >= date_trunc('month', current_date)::date;
```

