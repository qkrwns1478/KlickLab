# golden SQL 평가 — k-exaone_v2.5 (reasoning_effort=low)

- 실행: 2026-11-11T09:50:14+09:00
- 실행 정확도: **95.0%** (19/20)
- 난이도별: compare 83.3% (6), lookup 100.0% (14)
- 상태: match 19, mismatch 1
- 생성 지연(ms): 평균 18349, 중앙값 11180, 최대 51468
- 평균 토큰: 입력 1691, 출력 733 (추론 626)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 4296 | 172 |  |
| lookup-02 | match | 6281 | 260 |  |
| lookup-03 | match | 9984 | 304 |  |
| lookup-04 | match | 8078 | 331 |  |
| lookup-05 | match | 7235 | 316 |  |
| lookup-06 | match | 8750 | 391 |  |
| lookup-07 | match | 11891 | 447 |  |
| lookup-08 | match | 5530 | 272 |  |
| lookup-09 | match | 5375 | 241 |  |
| lookup-10 | match | 4672 | 220 |  |
| lookup-11 | match | 21922 | 769 |  |
| lookup-12 | match | 12641 | 531 |  |
| lookup-13 | match | 10468 | 417 |  |
| lookup-14 | match | 51468 | 1721 |  |
| compare-01 | match | 44436 | 1840 |  |
| compare-02 | match | 23234 | 996 |  |
| compare-03 | match | 16733 | 663 |  |
| compare-04 | match | 50406 | 2349 |  |
| compare-05 | mismatch | 41936 | 1521 | 행 수 불일치 (정답 1, 예측 2) |
| compare-06 | match | 21640 | 905 |  |

## 실패 문항

### compare-05 — mismatch

질문: 최근 7일과 그 전 7일의 일평균 순 방문자 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
SELECT '최근 7일' AS 기간, count(*)::numeric / 7 AS 일평균_순방문자수
FROM agg_daily_users
WHERE summary_date >= current_date - 7 AND summary_date < current_date
UNION ALL
SELECT '이전 7일', count(*)::numeric / 7
FROM agg_daily_users
WHERE summary_date >= current_date - 14 AND summary_date < current_date - 7
ORDER BY 기간
```

