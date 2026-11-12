# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-12T09:01:57+09:00 / phase4-rest11
- 모델: exaone / k-exaone_v2.5, 스키마 컨텍스트: prompt
- 실행 정확도: **40.0%** (2/5) — 공급자 오류로 평가 못 한 문항 6/11
- 난이도별: compare 25.0% (4), lookup 100.0% (1) / 스키마 요약 밖 지식 - (0)
- 상태: llm_error 6, match 2, mismatch 3
- 지연(ms): 평균 158265, 중앙값 158734, 최대 175813
- 평균 토큰: 입력 771, 출력 453 (추론 402)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-28 | match | 138375 | 952 |  |
| lookup-29 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-07 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-08 | mismatch | 175813 | 941 | 행 수 불일치 (정답 1, 예측 2) |
| compare-09 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-10 | match | 161827 | 774 |  |
| compare-11 | mismatch | 156577 | 995 | 행 수 불일치 (정답 3, 예측 6) |
| compare-12 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-13 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-14 | llm_error | 0 | 0 | LLM 응답 시간 초과 (ReadTimeout) |
| compare-15 | mismatch | 158734 | 1324 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-29 — llm_error

질문: 최근 7일 일별 문의 접수 건수 추이는?

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-07 — llm_error

질문: 지난주 대비 이번 주 기기 유형별 세션 수를 비교해줘

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-08 — mismatch

질문: 최근 7일과 그 전 7일의 nov_mega_sale 캠페인 세션 수를 비교해줘

사유: 행 수 불일치 (정답 1, 예측 2)

```sql
SELECT
  CASE
    WHEN summary_date >= current_date - 7 THEN '최근 7일'
    ELSE '이전 7일'
  END AS period,
  SUM(sessions) AS sessions
FROM agg_traffic_hourly
WHERE traffic_campaign = 'nov_mega_sale'
  AND summary_date >= current_date - 14
  AND summary_date < current_date
GROUP BY 1
ORDER BY MIN(summary_date)
```

### compare-09 — llm_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-11 — mismatch

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: 행 수 불일치 (정답 3, 예측 6)

```sql
SELECT
  (current_date - 15)::date AS summary_date,
  e.device_type,
  count(*) AS is_payment_count
FROM events e
WHERE e.event_name = 'is_payment'
  AND e.timestamp >= ((current_date - 15)::date)::timestamp
  AND e.timestamp < ((current_date - 14)::date)::timestamp
GROUP BY 1, 2
UNION ALL
SELECT
  (current_date - 14)::date AS summary_date,
  e.device_type,
  count(*) AS is_payment_count
FROM events e
WHERE e.event_name = 'is_payment'
  AND e.timestamp >= ((current_date - 14)::date)::timestamp
  AND e.timestamp < ((current_date - 13)::date)::timestamp
GROUP BY 1, 2
ORDER BY 1, 2
```

### compare-12 — llm_error

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-13 — llm_error

질문: 최근 7일과 그 전 7일의 유입 소스(traffic_source)별 전환 수를 비교해줘

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-14 — llm_error

질문: 최근 14일 일별 모바일과 데스크톱 세션 수를 날짜별 한 행에 나란히 보여줘

사유: LLM 응답 시간 초과 (ReadTimeout)

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT
  traffic_source,
  SUM(conversions) * 100.0 / NULLIF(SUM(sessions), 0) AS conversion_rate_pct
FROM agg_traffic_hourly
WHERE summary_date >= date_trunc('week', current_date)::date - 7
  AND summary_date < date_trunc('week', current_date)::date
GROUP BY traffic_source
HAVING SUM(sessions) >= 200
ORDER BY conversion_rate_pct DESC
LIMIT 3;
```

