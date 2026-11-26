# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:42:24+09:00 / single-prompt-r2
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: prompt
- 실행 정확도: **95.5%** (42/44)
- 난이도별: compare 93.3% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 75.0% (4)
- 상태: match 42, mismatch 2
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 3523, 중앙값 2524, 최대 13655
- 평균 토큰: 입력 1876, 출력 394 (추론 264)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 2157 | 90 |  |
| lookup-02 | match | 2547 | 182 |  |
| lookup-03 | match | 1610 | 133 |  |
| lookup-04 | match | 1891 | 126 |  |
| lookup-05 | match | 1719 | 143 |  |
| lookup-06 | match | 2547 | 187 |  |
| lookup-07 | match | 1375 | 133 |  |
| lookup-08 | match | 1967 | 155 |  |
| lookup-09 | match | 2047 | 147 |  |
| lookup-10 | match | 3000 | 323 |  |
| lookup-11 | match | 3516 | 377 |  |
| lookup-12 | match | 1952 | 177 |  |
| lookup-13 | match | 2391 | 215 |  |
| lookup-14 | match | 3625 | 372 |  |
| compare-01 | match | 8172 | 1100 |  |
| compare-02 | match | 2561 | 284 |  |
| compare-03 | match | 3094 | 367 |  |
| compare-04 | match | 7735 | 1059 |  |
| compare-05 | match | 6688 | 875 |  |
| compare-06 | match | 6469 | 825 |  |
| lookup-15 | match | 1858 | 150 |  |
| lookup-16 | match | 1750 | 165 |  |
| lookup-17 | match | 2500 | 204 |  |
| lookup-18 | match | 2079 | 181 |  |
| lookup-19 | match | 2016 | 135 |  |
| lookup-20 | match | 2719 | 268 |  |
| lookup-21 | match | 1890 | 159 |  |
| lookup-22 | mismatch | 5844 | 685 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 2344 | 174 |  |
| lookup-24 | match | 1875 | 155 |  |
| lookup-25 | match | 2421 | 218 |  |
| lookup-26 | match | 1436 | 143 |  |
| lookup-27 | match | 2061 | 152 |  |
| lookup-28 | match | 2782 | 279 |  |
| lookup-29 | match | 1734 | 155 |  |
| compare-07 | match | 4030 | 483 |  |
| compare-08 | match | 4563 | 578 |  |
| compare-09 | match | 3984 | 504 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 2594 | 243 |  |
| compare-11 | match | 8296 | 1196 |  |
| compare-12 | match | 7641 | 945 |  |
| compare-13 | match | 5485 | 708 |  |
| compare-14 | match | 2375 | 226 |  |
| compare-15 | mismatch | 13655 | 1955 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |

## 실패 문항

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH week_start AS (
    SELECT date_trunc('week', current_date)::date AS start_date
),
week_users AS (
    SELECT DISTINCT d.client_id
    FROM agg_daily_users AS d
    CROSS JOIN week_start AS w
    WHERE d.summary_date >= w.start_date - 7
      AND d.summary_date < w.start_date
),
prior_users AS (
    SELECT DISTINCT d.client_id
    FROM agg_daily_users AS d
    CROSS JOIN week_start AS w
    WHERE d.summary_date < w.start_date - 7
)
SELECT
    COUNT(*) FILTER (WHERE p.client_id IS NULL) AS 신규_방문자_수,
    COUNT(*) FILTER (WHERE p.client_id IS NOT NULL) AS 재방문자_수
FROM week_users AS u
LEFT JOIN prior_users AS p
    ON p.client_id = u.client_id;
```

### compare-15 — mismatch

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH traffic AS (
    SELECT
        traffic_source,
        SUM(sessions) AS sessions
    FROM agg_traffic_hourly
    WHERE summary_date >= date_trunc('week', current_date)::date - 7
      AND summary_date < date_trunc('week', current_date)::date
    GROUP BY traffic_source
),
paid_sessions AS (
    SELECT
        traffic_source,
        COUNT(DISTINCT session_id) AS paid_sessions
    FROM events
    WHERE timestamp >= date_trunc('week', current_date)::date - 7
      AND timestamp < date_trunc('week', current_date)::date
      AND event_name = 'is_payment'
    GROUP BY traffic_source
)
SELECT
    t.traffic_source,
    t.sessions AS session_count,
    COALESCE(p.paid_sessions, 0) AS paid_session_count,
    COALESCE(p.paid_sessions, 0) * 100.0 / NULLIF(t.sessions, 0) AS paid_session_rate_pct
FROM traffic AS t
LEFT JOIN paid_sessions AS p
    ON p.traffic_source IS NOT DISTINCT FROM t.traffic_source
WHERE t.sessions >= 200
ORDER BY paid_session_rate_pct DESC, t.traffic_source
LIMIT 3;
```

