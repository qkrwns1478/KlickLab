# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:42:24+09:00 / single-rag-expand1-r1
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **100.0%** (44/44)
- 난이도별: compare 100.0% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: match 44
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 3029, 중앙값 2351, 최대 9530
- 평균 토큰: 입력 2348, 출력 329 (추론 212)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1454 | 74 |  |
| lookup-02 | match | 1891 | 139 |  |
| lookup-03 | match | 1858 | 124 |  |
| lookup-04 | match | 1686 | 134 |  |
| lookup-05 | match | 2500 | 157 |  |
| lookup-06 | match | 2358 | 222 |  |
| lookup-07 | match | 1954 | 134 |  |
| lookup-08 | match | 1891 | 104 |  |
| lookup-09 | match | 1500 | 107 |  |
| lookup-10 | match | 2016 | 165 |  |
| lookup-11 | match | 3375 | 366 |  |
| lookup-12 | match | 1858 | 163 |  |
| lookup-13 | match | 2217 | 190 |  |
| lookup-14 | match | 2766 | 296 |  |
| compare-01 | match | 3766 | 524 |  |
| compare-02 | match | 2500 | 228 |  |
| compare-03 | match | 4514 | 538 |  |
| compare-04 | match | 2938 | 295 |  |
| compare-05 | match | 8422 | 1237 |  |
| compare-06 | match | 5344 | 737 |  |
| lookup-15 | match | 1625 | 97 |  |
| lookup-16 | match | 1985 | 129 |  |
| lookup-17 | match | 2139 | 160 |  |
| lookup-18 | match | 1938 | 133 |  |
| lookup-19 | match | 1750 | 100 |  |
| lookup-20 | match | 1532 | 120 |  |
| lookup-21 | match | 1889 | 168 |  |
| lookup-22 | match | 3155 | 365 |  |
| lookup-23 | match | 1953 | 115 |  |
| lookup-24 | match | 1686 | 117 |  |
| lookup-25 | match | 1672 | 99 |  |
| lookup-26 | match | 1717 | 139 |  |
| lookup-27 | match | 2344 | 188 |  |
| lookup-28 | match | 9530 | 1203 |  |
| lookup-29 | match | 2390 | 284 |  |
| compare-07 | match | 4500 | 631 |  |
| compare-08 | match | 3405 | 491 |  |
| compare-09 | match | 5078 | 614 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 4750 | 571 |  |
| compare-11 | match | 4686 | 598 |  |
| compare-12 | match | 2875 | 307 |  |
| compare-13 | match | 3046 | 318 |  |
| compare-14 | match | 2827 | 297 |  |
| compare-15 | match | 7984 | 1306 |  |
