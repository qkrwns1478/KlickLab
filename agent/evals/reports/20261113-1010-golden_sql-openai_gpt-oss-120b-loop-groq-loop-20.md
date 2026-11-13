# golden SQL 평가 (Tool Loop)

- 실행: 2026-11-13T10:10:10+09:00 / groq-loop-20
- 모델: groq / openai/gpt-oss-120b, 스키마 컨텍스트: prompt
- 실행 정확도: **85.0%** (17/20)
- 난이도별: compare 66.7% (6), lookup 92.9% (14) / 스키마 요약 밖 지식 - (0)
- 상태: match 17, mismatch 3
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 40942, 중앙값 44766, 최대 124077
- 평균 토큰: 입력 5232, 출력 1104 (추론 0)
- 실행한 SQL 중 하나라도 정답: 85.0%

| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compare | 5 | 2.4 | 3 | 6,751 | 2,034 | 0.0 | 58,749 / 54,922 | 0.0% | 100.0% | 0 |
| lookup | 15 | 1.7 | 2 | 4,725 | 794 | 0.0 | 35,007 / 37,796 | 0.0% | 100.0% | 0 |
| 전체 | 20 | 1.9 | 2.2 | 5,232 | 1,104 | 0.0 | 40,942 / 44,766 | 0.0% | 100.0% | 0 |

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 4812 | 391 |  |
| lookup-02 | match | 54922 | 1673 |  |
| lookup-03 | match | 48656 | 849 |  |
| lookup-04 | match | 124077 | 2511 |  |
| lookup-05 | match | 33781 | 895 |  |
| lookup-06 | match | 49186 | 1104 |  |
| lookup-07 | match | 24452 | 585 |  |
| lookup-08 | match | 30047 | 348 |  |
| lookup-09 | mismatch | 37796 | 197 | 행 수 불일치 (정답 3, 예측 13) |
| lookup-10 | match | 45156 | 972 |  |
| lookup-11 | match | 53891 | 515 |  |
| lookup-12 | match | 45515 | 858 |  |
| lookup-13 | match | 17687 | 471 |  |
| lookup-14 | match | 46843 | 912 |  |
| compare-01 | mismatch | 50031 | 2819 | 정답 3번째 컬럼과 값이 같은 컬럼이 없음 |
| compare-02 | match | 44375 | 1227 |  |
| compare-03 | match | 21796 | 1209 |  |
| compare-04 | match | 21110 | 1370 |  |
| compare-05 | match | 56108 | 1778 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | mismatch | 8609 | 1390 | 정답 3번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-09 — mismatch

질문: 어제 성별 방문자 수는?

사유: 행 수 불일치 (정답 3, 예측 13)

```sql
SELECT gender, users FROM agg_user_session_daily WHERE summary_date = current_date - 1 ORDER BY gender;
```

### compare-01 — mismatch

질문: 지난주 대비 이번 주 유입 소스(traffic_source)별 세션 수를 비교해줘

사유: 정답 3번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH last_week AS (
 SELECT traffic_source, sum(sessions) AS last_week_sessions
 FROM agg_traffic_hourly
 WHERE summary_date >= date_trunc('week', current_date)::date - interval '7 day'
   AND summary_date < date_trunc('week', current_date)::date
 GROUP BY traffic_source
), this_week AS (
 SELECT traffic_source, sum(sessions) AS this_week_sessions
 FROM agg_traffic_hourly
 WHERE summary_date >= date_trunc('week', current_date)::date
   AND summary_date < current_date
 GROUP BY traffic_source
)
SELECT coalesce(lw.traffic_source, tw.traffic_source) AS traffic_source,
       coalesce(lw.last_week_sessions, 0) AS last_week_sessions,
       coalesce(tw.this_week_sessions, 0) AS this_week_sessions,
       CASE WHEN coalesce(lw.last_week_sessions, 0) = 0 THEN NULL
            ELSE round((coalesce(tw.this_week_sessions,0) - coalesce(lw.last_week_sessions,0))::numeric 
               / coalesce(lw.last_week_sessions,0) * 100, 2)
       END AS pct_change
FROM last_week lw
FULL OUTER JOIN this_week tw
  ON lw.traffic_source = tw.traffic_source
ORDER BY traffic_source;
```

### compare-06 — mismatch

질문: 지난주 대비 이번 주 이벤트 종류별 발생 건수 변화를 보여줘

사유: 정답 3번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH this_week AS (
   SELECT event_name, SUM(event_count) AS this_week_count
   FROM agg_event_daily
   WHERE summary_date >= date_trunc('week', current_date)::date
     AND summary_date < current_date
   GROUP BY event_name
),
last_week AS (
   SELECT event_name, SUM(event_count) AS last_week_count
   FROM agg_event_daily
   WHERE summary_date >= (date_trunc('week', current_date)::date - interval '7 days')
     AND summary_date < date_trunc('week', current_date)::date
   GROUP BY event_name
)
SELECT COALESCE(lw.event_name, tw.event_name) AS event_name,
       COALESCE(lw.last_week_count, 0) AS last_week_count,
       COALESCE(tw.this_week_count, 0) AS this_week_count,
       (COALESCE(tw.this_week_count, 0) - COALESCE(lw.last_week_count, 0)) AS diff,
       CASE WHEN COALESCE(lw.last_week_count, 0) = 0 THEN NULL
            ELSE ROUND(((COALESCE(tw.this_week_count, 0)::numeric - COALESCE(lw.last_week_count, 0)) / COALESCE(lw.last_week_count, 0)) * 100, 2)
       END AS pct_change
FROM last_week lw
FULL OUTER JOIN this_week tw ON lw.event_name = tw.event_name
ORDER BY event_name;
```

