# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-12T15:12:11+09:00 / phase4-local-medium
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: prompt
- 실행 정확도: **95.0%** (19/20)
- 난이도별: compare 83.3% (6), lookup 100.0% (14) / 스키마 요약 밖 지식 - (0)
- 상태: match 19, mismatch 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 24299, 중앙값 21577, 최대 74875
- 평균 토큰: 입력 11438, 출력 1903 (추론 0)
- 실행한 SQL 중 하나라도 정답: 95.0%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 3 | 4.7 | 6.3 | 19,071 | 3,472 | 0.0 | 45,844 / 34,125 | 33.3% | 100.0% | 0.3 |
| lookup | 17 | 3.5 | 3.8 | 10,092 | 1,626 | 0.0 | 20,498 / 19,311 | 0.0% | 100.0% | 0 |
| 전체 | 20 | 3.7 | 4.2 | 11,438 | 1,903 | 0.0 | 24,300 / 21,577 | 5.0% | 100.0% | 0.1 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 12843 | 994 |  |
| lookup-02 | match | 25375 | 2043 |  |
| lookup-03 | match | 38109 | 2586 |  |
| lookup-04 | match | 19311 | 1590 |  |
| lookup-05 | match | 11608 | 937 |  |
| lookup-06 | match | 11202 | 903 |  |
| lookup-07 | match | 24155 | 1968 |  |
| lookup-08 | match | 22172 | 1823 |  |
| lookup-09 | match | 10780 | 870 |  |
| lookup-10 | match | 12719 | 1023 |  |
| lookup-11 | match | 18906 | 1495 |  |
| lookup-12 | match | 21343 | 1728 |  |
| lookup-13 | match | 18156 | 1401 |  |
| lookup-14 | match | 7922 | 616 |  |
| compare-01 | match | 34125 | 2703 |  |
| compare-02 | match | 21811 | 1737 |  |
| compare-03 | match | 44719 | 3680 |  |
| compare-04 | match | 27327 | 2253 |  |
| compare-05 | match | 28531 | 2367 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | mismatch | 74875 | 5345 | 행 수 불일치 (정답 6, 예측 0) |

## 실패 문항

### compare-06 — mismatch

질문: 지난주 대비 이번 주 이벤트 종류별 발생 건수 변화를 보여줘

사유: 행 수 불일치 (정답 6, 예측 0)

```sql
WITH week_bounds AS (
  SELECT date_trunc('week', current_date)::date AS week_start,
         date_trunc('week', current_date)::date + interval '7' AS week_end
),
  events_this_week AS (
    SELECT event_name, count(*) AS cnt
    FROM events
    WHERE timestamp >= (SELECT week_start FROM week_bounds) AND timestamp < (SELECT week_end FROM week_bounds)
    GROUP BY event_name
  ),
  events_last_week AS (
    SELECT event_name, count(*) AS cnt
    FROM events
    WHERE timestamp >= (SELECT week_start FROM week_bounds) - interval '7'
      AND timestamp < (SELECT week_start FROM week_bounds)
    GROUP BY event_name
  )
SELECT
  coalesce(ew.event_name, el.event_name) AS event_name,
  coalesce(ew.cnt,0) AS this_week_count,
  coalesce(el.cnt,0) AS last_week_count,
  (coalesce(ew.cnt,0) - coalesce(el.cnt,0)) AS diff,
  CASE WHEN coalesce(el.cnt,0)=0 THEN NULL
       ELSE 100.0 * ( (coalesce(ew.cnt,0) - coalesce(el.cnt,0)) / NULLIF(coalesce(el.cnt,0),0) )
  END AS pct_change
FROM events_this_week ew
FULL JOIN events_last_week el ON ew.event_name = el.event_name
ORDER BY diff DESC;
```

