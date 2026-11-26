# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-12T14:28:25+09:00 / phase1-local
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **90.0%** (18/20)
- 난이도별: compare 83.3% (6), lookup 92.9% (14) / 스키마 요약 밖 지식 - (0)
- 상태: match 18, mismatch 1, no_sql 1
- 지연(ms): 평균 33659, 중앙값 20656, 최대 151015
- 평균 토큰: 입력 10755, 출력 2610 (추론 0)
- 실행한 SQL 중 하나라도 정답: 90.0%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 3 | 2.7 | 4.7 | 13,232 | 8,722 | 0.0 | 106,442 / 89,125 | 33.3% | 100.0% | 0 |
| lookup | 17 | 3.5 | 3.8 | 10,318 | 1,531 | 0.0 | 20,815 / 18,594 | 0.0% | 100.0% | 0 |
| 전체 | 20 | 3.4 | 3.9 | 10,755 | 2,610 | 0.0 | 33,659 / 20,656 | 5.0% | 100.0% | 0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 14609 | 647 |  |
| lookup-02 | match | 23000 | 1638 |  |
| lookup-03 | match | 14750 | 1204 |  |
| lookup-04 | match | 13406 | 1089 |  |
| lookup-05 | match | 13610 | 1102 |  |
| lookup-06 | match | 25391 | 1759 |  |
| lookup-07 | match | 31375 | 1632 |  |
| lookup-08 | match | 10452 | 833 |  |
| lookup-09 | match | 5452 | 430 |  |
| lookup-10 | match | 21077 | 1735 |  |
| lookup-11 | match | 36015 | 2963 |  |
| lookup-12 | match | 9812 | 781 |  |
| lookup-13 | mismatch | 52921 | 3526 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-14 | match | 16891 | 1381 |  |
| compare-01 | match | 79187 | 6545 |  |
| compare-02 | match | 20234 | 1660 |  |
| compare-03 | match | 26265 | 2138 |  |
| compare-04 | match | 18594 | 1511 |  |
| compare-05 | no_sql | 151015 | 12329 | 성공한 SQL 없음 (budget_exhausted) |
| compare-06 | match | 89125 | 7292 |  |

## 실패 문항

### lookup-13 — mismatch

질문: 최근 7일 페이지뷰 100회 이상인 페이지 중 평균 체류 시간(초)이 가장 긴 5개는?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT page_path, time_on_page_sum, page_views, time_on_page_sum::numeric / NULLIF(page_views, 0) AS avg_time_on_page FROM agg_page_daily WHERE summary_date >= current_date - 7 AND summary_date < current_date AND page_views >= 100 ORDER BY avg_time_on_page DESC LIMIT 5;
```

### compare-05 — no_sql

질문: 최근 7일과 그 전 7일의 일평균 순 방문자 수를 비교해줘

사유: 성공한 SQL 없음 (budget_exhausted)

