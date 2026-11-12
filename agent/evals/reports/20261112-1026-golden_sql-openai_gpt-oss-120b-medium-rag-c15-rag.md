# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-12T10:26:50+09:00 / c15-rag
- 모델: groq / openai/gpt-oss-120b, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **0.0%** (0/1)
- 난이도별: compare 0.0% (1) / 스키마 요약 밖 지식 - (0)
- 상태: mismatch 1
- 지연(ms): 평균 1827, 중앙값 1827, 최대 1827
- 평균 토큰: 입력 2323, 출력 565 (추론 442)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| compare-15 | mismatch | 1827 | 565 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

넣은 문서: table/agg_traffic_hourly, table/agg_funnel_links_daily, metric/payment_session_rate, metric/sessions, glossary/traffic_channels, glossary/period_week, glossary/event_names, example/landing_bounce_by_source

```sql
SELECT
    traffic_source,
    SUM(sessions) AS total_sessions,
    SUM(conversions) * 100.0 / NULLIF(SUM(sessions), 0) AS payment_session_rate_pct
FROM agg_traffic_hourly
WHERE summary_date >= date_trunc('week', current_date)::date - 7
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY traffic_source
HAVING SUM(sessions) >= 200
ORDER BY payment_session_rate_pct DESC
LIMIT 3;
```

