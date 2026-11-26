# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-13T09:52:59+09:00 / altare-single-prompt
- 모델: altare / gpt-oss-120b, 스키마 컨텍스트: prompt
- 실행 정확도: **87.9%** (29/33) — 공급자 오류로 평가 못 한 문항 11/44
- 난이도별: compare 100.0% (6), lookup 85.2% (27) / 스키마 요약 밖 지식 75.0% (4)
- 상태: llm_error 11, match 29, mismatch 2, no_sql 2
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 22927, 중앙값 13500, 최대 156108
- 평균 토큰: 입력 1389, 출력 1306 (추론 0)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 4484 | 355 |  |
| lookup-02 | match | 11484 | 612 |  |
| lookup-03 | match | 7500 | 385 |  |
| lookup-04 | match | 26686 | 736 |  |
| lookup-05 | no_sql | 156108 | 16384 | 출력 잘림 |
| lookup-06 | match | 13500 | 689 |  |
| lookup-07 | match | 11609 | 649 |  |
| lookup-08 | mismatch | 13922 | 742 | 정답 1번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-09 | match | 14641 | 502 |  |
| lookup-10 | match | 9905 | 534 |  |
| lookup-11 | match | 13952 | 495 |  |
| lookup-12 | match | 7296 | 614 |  |
| lookup-13 | match | 17452 | 763 |  |
| lookup-14 | match | 22172 | 1234 |  |
| compare-01 | match | 34219 | 1793 |  |
| compare-02 | match | 9625 | 905 |  |
| compare-03 | match | 19469 | 1042 |  |
| compare-04 | match | 20016 | 1926 |  |
| compare-05 | match | 11000 | 1215 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 33750 | 1765 |  |
| lookup-15 | match | 7984 | 352 |  |
| lookup-16 | match | 9563 | 418 |  |
| lookup-17 | match | 14172 | 619 |  |
| lookup-18 | match | 12297 | 721 |  |
| lookup-19 | match | 13686 | 572 |  |
| lookup-20 | match | 7702 | 388 |  |
| lookup-21 | match | 6172 | 531 |  |
| lookup-22 | mismatch | 31125 | 1762 | 정답 2번째 컬럼과 값이 같은 컬럼이 없음 |
| lookup-23 | match | 11280 | 603 |  |
| lookup-24 | match | 8405 | 440 |  |
| lookup-25 | match | 21702 | 671 |  |
| lookup-26 | match | 6905 | 675 |  |
| lookup-27 | no_sql | 146796 | 16384 | 출력 잘림 |
| lookup-28 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| lookup-29 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-07 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-08 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-09 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-10 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-11 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-12 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-13 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-14 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |
| compare-15 | llm_error | 0 | 0 | LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access." |

## 실패 문항

### lookup-05 — no_sql

질문: 지난주 유입 소스(traffic_source)별 세션 수는?

사유: 출력 잘림

### lookup-08 — mismatch

질문: 이번 달 결제 완료 건수는?

사유: 정답 1번째 컬럼과 값이 같은 컬럼이 없음

```sql
SELECT COALESCE(SUM(event_count), 0) AS payment_completed_count
FROM agg_event_daily
WHERE summary_date >= date_trunc('month', current_date)::date
  AND summary_date < current_date
  AND event_name = 'is_payment';
```

### lookup-22 — mismatch

질문: 지난주 신규 방문자 수와 재방문자 수는?

사유: 정답 2번째 컬럼과 값이 같은 컬럼이 없음

```sql
WITH
    period AS (
        SELECT 
            date_trunc('week', current_date)::date - 7 AS start_date,
            date_trunc('week', current_date)::date       AS end_date
    ),
    first_visits AS (
        SELECT client_id, MIN(summary_date) AS first_date
        FROM agg_daily_users
        GROUP BY client_id
    ),
    last_week_active AS (
        SELECT DISTINCT client_id
        FROM agg_daily_users a
        CROSS JOIN period p
        WHERE a.summary_date >= p.start_date
          AND a.summary_date <  p.end_date
    )
SELECT
    SUM(CASE 
            WHEN fv.first_date >= p.start_date 
             AND fv.first_date <  p.end_date THEN 1 
            ELSE 0 
        END) AS new_visitors,
    SUM(CASE 
            WHEN fv.first_date < p.start_date THEN 1 
            ELSE 0 
        END) AS returning_visitors
FROM last_week_active l
JOIN first_visits fv ON fv.client_id = l.client_id
CROSS JOIN period p;
```

### lookup-27 — no_sql

질문: 지난주 /checkout 에서 /checkout/success 로 이동한 세션 수는?

사유: 출력 잘림

### lookup-28 — llm_error

질문: 15일 전 모바일 기기의 결제 완료 건수는?

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### lookup-29 — llm_error

질문: 최근 7일 일별 문의 접수 건수 추이는?

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-07 — llm_error

질문: 지난주 대비 이번 주 기기 유형별 세션 수를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-08 — llm_error

질문: 최근 7일과 그 전 7일의 nov_mega_sale 캠페인 세션 수를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-09 — llm_error

질문: 최근 28일 주말(토·일)과 평일의 하루 평균 세션 수를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-10 — llm_error

질문: 최근 28일 요일별(ISO 요일 번호, 월=1) 이메일(email) 매체 유입 세션 수는?

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-11 — llm_error

질문: 15일 전과 14일 전의 기기 유형별 결제 완료 건수를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-12 — llm_error

질문: 지난달과 이번 달의 일평균 페이지뷰를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-13 — llm_error

질문: 최근 7일과 그 전 7일의 유입 소스(traffic_source)별 전환 수를 비교해줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-14 — llm_error

질문: 최근 14일 일별 모바일과 데스크톱 세션 수를 날짜별 한 행에 나란히 보여줘

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

### compare-15 — llm_error

질문: 지난주 세션 200개 이상인 유입 소스(traffic_source) 중 결제한 세션 비율(%)이 가장 높은 3개는?

사유: LLM 응답 오류 402: {"error":{"message":"Altare Inference is no longer included with Always Free: we don’t have the capacity to keep offering it for free. Altare Plus and Business teams keep their access."

