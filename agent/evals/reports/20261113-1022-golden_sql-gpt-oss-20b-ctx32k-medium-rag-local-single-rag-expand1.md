# golden SQL 평가 (단일 턴, effort=medium)

- 실행: 2026-11-13T10:22:22+09:00 / local-single-rag-expand1
- 모델: local / gpt-oss-20b-ctx32k, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **97.7%** (43/44)
- 난이도별: compare 100.0% (15), lookup 96.6% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: match 43, no_sql 1
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 4문항
- 지연(ms): 평균 7039, 중앙값 6531, 최대 19702
- 평균 토큰: 입력 2388, 출력 554 (추론 0)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 3516 | 229 |  |
| lookup-02 | match | 3875 | 286 |  |
| lookup-03 | match | 4062 | 303 |  |
| lookup-04 | match | 3765 | 283 |  |
| lookup-05 | match | 5686 | 439 |  |
| lookup-06 | match | 6484 | 503 |  |
| lookup-07 | match | 8234 | 642 |  |
| lookup-08 | match | 4875 | 370 |  |
| lookup-09 | match | 2968 | 208 |  |
| lookup-10 | match | 4952 | 373 |  |
| lookup-11 | match | 6141 | 465 |  |
| lookup-12 | match | 5562 | 428 |  |
| lookup-13 | match | 9110 | 732 |  |
| lookup-14 | match | 8672 | 707 |  |
| compare-01 | match | 19702 | 1618 |  |
| compare-02 | match | 7655 | 601 |  |
| compare-03 | match | 5219 | 400 |  |
| compare-04 | match | 12530 | 1008 |  |
| compare-05 | match | 7047 | 595 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-06 | match | 9702 | 785 |  |
| lookup-15 | match | 2594 | 180 |  |
| lookup-16 | match | 4061 | 310 |  |
| lookup-17 | match | 6578 | 516 |  |
| lookup-18 | match | 4702 | 357 |  |
| lookup-19 | match | 3938 | 286 |  |
| lookup-20 | match | 4547 | 345 |  |
| lookup-21 | match | 7734 | 621 |  |
| lookup-22 | match | 9110 | 735 |  |
| lookup-23 | match | 7187 | 568 |  |
| lookup-24 | match | 3062 | 214 |  |
| lookup-25 | match | 4297 | 326 |  |
| lookup-26 | match | 5156 | 389 |  |
| lookup-27 | match | 8203 | 651 |  |
| lookup-28 | no_sql | 6719 | 549 | 지급한 결제 건수를 기기(모바일)별로 구분하려면 이벤트 기록에 기기 정보가 필요하지만 agg_event_daily에는 device_type이 없으며, agg_user_session_hourly와 agg_event_daily를 조인하기 위한 공통 컬럼(예: client_id, 세션 ID 등)이 제공되지 않으므로 모바일 기기 결제 건수를 정확히 산출할 수 없습니다. |
| lookup-29 | match | 5688 | 441 |  |
| compare-07 | match | 8750 | 684 |  |
| compare-08 | match | 13577 | 1108 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-09 | match | 6983 | 549 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 5296 | 406 |  |
| compare-11 | match | 11640 | 937 |  |
| compare-12 | match | 10016 | 807 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-13 | match | 11702 | 950 |  |
| compare-14 | match | 7406 | 575 |  |
| compare-15 | match | 11000 | 875 |  |

## 실패 문항

### lookup-28 — no_sql

질문: 15일 전 모바일 기기의 결제 완료 건수는?

사유: 지급한 결제 건수를 기기(모바일)별로 구분하려면 이벤트 기록에 기기 정보가 필요하지만 agg_event_daily에는 device_type이 없으며, agg_user_session_hourly와 agg_event_daily를 조인하기 위한 공통 컬럼(예: client_id, 세션 ID 등)이 제공되지 않으므로 모바일 기기 결제 건수를 정확히 산출할 수 없습니다.

넣은 문서: table/agg_event_daily, table/agg_user_session_hourly, metric/payments, metric/revenue, glossary/devices, glossary/event_names, glossary/period_day, example/daily_revenue_trend, table/agg_traffic_hourly

