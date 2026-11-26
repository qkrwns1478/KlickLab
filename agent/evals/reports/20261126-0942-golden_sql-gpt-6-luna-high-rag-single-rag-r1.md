# golden SQL 평가 (단일 턴, effort=high)

- 실행: 2026-11-26T09:42:24+09:00 / single-rag-r1
- 모델: openai / gpt-6-luna, 스키마 컨텍스트: rag (할당량 table:2,metric:2,glossary:3,example:1)
- 실행 정확도: **100.0%** (44/44)
- 난이도별: compare 100.0% (15), lookup 100.0% (29) / 스키마 요약 밖 지식 100.0% (4)
- 상태: match 44
- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: 1문항
- 지연(ms): 평균 2890, 중앙값 2282, 최대 7969
- 평균 토큰: 입력 2141, 출력 309 (추론 192)

| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |
| --- | --- | --- | --- | --- |
| lookup-01 | match | 1655 | 75 |  |
| lookup-02 | match | 1922 | 144 |  |
| lookup-03 | match | 2172 | 158 |  |
| lookup-04 | match | 1485 | 132 |  |
| lookup-05 | match | 1860 | 141 |  |
| lookup-06 | match | 2389 | 188 |  |
| lookup-07 | match | 2077 | 147 |  |
| lookup-08 | match | 1842 | 106 |  |
| lookup-09 | match | 2125 | 165 |  |
| lookup-10 | match | 2858 | 245 |  |
| lookup-11 | match | 3952 | 419 |  |
| lookup-12 | match | 1608 | 156 |  |
| lookup-13 | match | 2172 | 242 |  |
| lookup-14 | match | 2938 | 302 |  |
| compare-01 | match | 6327 | 930 |  |
| compare-02 | match | 1608 | 168 |  |
| compare-03 | match | 3750 | 418 |  |
| compare-04 | match | 3266 | 398 |  |
| compare-05 | match | 4313 | 596 |  |
| compare-06 | match | 4266 | 600 |  |
| lookup-15 | match | 1530 | 102 |  |
| lookup-16 | match | 1766 | 119 |  |
| lookup-17 | match | 2235 | 199 |  |
| lookup-18 | match | 1842 | 117 |  |
| lookup-19 | match | 2109 | 108 |  |
| lookup-20 | match | 1875 | 169 |  |
| lookup-21 | match | 1719 | 157 |  |
| lookup-22 | match | 3905 | 463 |  |
| lookup-23 | match | 2328 | 191 |  |
| lookup-24 | match | 1561 | 104 |  |
| lookup-25 | match | 1969 | 138 |  |
| lookup-26 | match | 1609 | 130 |  |
| lookup-27 | match | 2047 | 174 |  |
| lookup-28 | match | 3342 | 403 |  |
| lookup-29 | match | 3015 | 347 |  |
| compare-07 | match | 3125 | 292 |  |
| compare-08 | match | 3765 | 547 |  |
| compare-09 | match | 4234 | 527 | 전치 허용: 정답의 열을 행으로 반환 |
| compare-10 | match | 5796 | 771 |  |
| compare-11 | match | 4609 | 533 |  |
| compare-12 | match | 2922 | 295 |  |
| compare-13 | match | 4078 | 481 |  |
| compare-14 | match | 3233 | 375 |  |
| compare-15 | match | 7969 | 1106 |  |
