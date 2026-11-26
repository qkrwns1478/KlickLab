# 지식 베이스 검색 평가 — 할당량 table:2,metric:2,glossary:3,example:1

- 실행: 2026-11-12T10:57:43+09:00
- 필요한 문서 = 정답 SQL 의 테이블 + 문항 knowledge 라벨(지표·용어)

| 방식 | 재현율 | 전부 찾은 문항 | table | metric | glossary | 컨텍스트 평균(자) | 지연 평균(ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid | 97.3% | 40/44 | 93.2% | 97.4% | 100.0% | 3952 | 308 |

## 놓친 문서 — hybrid

- lookup-13: metric/avg_time_on_page
- lookup-14: table/events
- lookup-18: table/agg_user_session_hourly
- lookup-28: table/events
