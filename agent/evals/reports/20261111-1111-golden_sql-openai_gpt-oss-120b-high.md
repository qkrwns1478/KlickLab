# golden SQL 평가 — openai/gpt-oss-120b (reasoning_effort=high)

- 실행: 2026-11-11T11:11:31+09:00
- 실행 정확도: **95.0%** (19/20)
- 난이도별: compare 83.3% (6), lookup 100.0% (14)
- 상태: match 19, rejected 1
- 생성 지연(ms): 평균 16819, 중앙값 15124, 최대 31561
- 평균 토큰: 입력 1860, 출력 1114 (추론 992)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1516 | 451 |  |
| lookup-02 | match | 15186 | 433 |  |
| lookup-03 | match | 15266 | 735 |  |
| lookup-04 | match | 14828 | 543 |  |
| lookup-05 | match | 14641 | 489 |  |
| lookup-06 | match | 16547 | 1144 |  |
| lookup-07 | match | 13812 | 624 |  |
| lookup-08 | match | 15452 | 803 |  |
| lookup-09 | match | 14765 | 779 |  |
| lookup-10 | match | 15063 | 716 |  |
| lookup-11 | match | 30016 | 765 |  |
| lookup-12 | match | 14922 | 788 |  |
| lookup-13 | match | 14859 | 552 |  |
| lookup-14 | match | 16484 | 1443 |  |
| compare-01 | match | 31561 | 1857 |  |
| compare-02 | match | 13000 | 1073 |  |
| compare-03 | match | 14937 | 1159 |  |
| compare-04 | rejected | 20188 | 3648 | events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요. |
| compare-05 | match | 27827 | 1919 |  |
| compare-06 | match | 15516 | 2357 |  |

## 실패 문항

### compare-04 — rejected

질문: 최근 7일 기기 유형별 결제 전환율(%)을 알려줘. 결제(is_payment) 이벤트가 있었던 세션의 비율로 계산해줘

사유: events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. 일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요.

```sql
WITH session_starts AS (
    SELECT
        session_id,
        MIN(timestamp) AS session_start,
        MIN(device_type) AS device_type
    FROM events
    WHERE timestamp < current_date
    GROUP BY session_id
    HAVING MIN(timestamp) >= current_date - interval '7 days'
       AND MIN(timestamp) < current_date
),
payment_sessions AS (
    SELECT
        ss.device_type,
        COUNT(DISTINCT ss.session_id) AS payment_sessions
    FROM session_starts ss
    JOIN events e
      ON e.session_id = ss.session_id
     AND e.event_name = 'is_payment'
     AND e.timestamp >= current_date - interval '7 days'
     AND e.timestamp < current_date
    GROUP BY ss.device_type
),
total_sessions AS (
    SELECT
        device_type,
        SUM(sessions) AS total_sessions
    FROM agg_user_session_hourly
    WHERE summary_date >= current_date - 7
      AND summary_date < current_date
    GROUP BY device_type
)
SELECT
    COALESCE(t.device_type, p.device_type) AS device_type,
    ROUND(
        COALESCE(p.payment_sessions, 0)::numeric * 100.0
        / NULLIF(COALESCE(t.total_sessions, 0), 0),
        2
    ) AS conversion_rate_percent
FROM total_sessions t
FULL OUTER JOIN payment_sessions p
  ON t.device_type = p.device_type
ORDER BY device_type;
```

