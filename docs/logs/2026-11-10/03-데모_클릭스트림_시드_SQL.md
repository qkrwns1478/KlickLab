# 데모 클릭스트림 시드 SQL 작성

## 요청

PostgreSQL에 데이터가 없고 수집 서버도 내려가 실제 데이터를 받을 수 없으므로, 대시보드에서 의미 있는 분석이 가능한 클릭스트림 데이터셋을 만드는 SQL 파일 생성

## 결과물

`backend/seed/clickstream_seed.sql` (Flyway 경로 밖이라 자동 실행되지 않음)

```bash
docker exec -i klicklab-postgres psql -U klicklab -d klicklab -v ON_ERROR_STOP=1 < seed/clickstream_seed.sql
```

- 단일 트랜잭션, `setseed` 고정이라 같은 날 실행하면 같은 데이터
- 데모 sdk_key(`klicklab-demo-sdk-key-0001`)의 events·agg_*·집계 테이블을 지우고 다시 생성 (멱등)
- 기간 내 `rollup_runs`를 지워 앱 기동 시 백필 대상이 되도록 함
- 계정 `demo@klicklab.dev` / `demo1234!` (pgcrypto `crypt(..., gen_salt('bf', 10))`, BCrypt 호환), `conversion_events`(is_payment·is_signup 활성), `event_button` 2건 생성

## 생성 방식

| 단계 | 내용 |
| --- | --- |
| 방문자 | 3만 명 후보: 성별·연령·지역(17개 시도)·기기→OS→브라우저 연쇄 분포, 32% 회원(user_id), 유형(기존/캠페인/신규) |
| 방문 | 방문자별 방문 횟수(회원일수록 많음)와 지수분포 간격, 요일별 방문 확률 |
| 세션 | 기기별 시간대 분포, 유입 채널(재방문은 direct 비중↑, 화요일 email↑), 채널·회원·기기에 따른 전환 의도 3단계 |
| 페이지 이동 | 재귀 CTE 마르코프 체인 (15개 페이지 + EXIT, 의도 수준별 전이 확률), 상품 상세는 Zipf 분포 상품 ID |
| 이벤트 | page_view(체류 시간·referrer), 페이지별 auto_click(한글 요소명), 이동 클릭, add_to_cart, is_payment(주문금액), is_signup, contact_submit |

심어 둔 패턴: 점심·저녁 피크, 주말 증가, 후반 성장, 최근 2~8일 전 `nov_mega_sale` 캠페인, 15일 전 모바일 결제 장애(해당 일 모바일 결제 0건), 채널별 전환율 차이(email·naver cpc 높음, instagram·youtube 낮음)

## 검증

실제 DB에서 `COMMIT` → `ROLLBACK` 사본으로 실행 (약 7초, DB 변경 없음)

- 이벤트 265,313 / 세션 33,677 / 방문자 21,008 / 페이지뷰 92,042 / 클릭 167,217 / 결제 1,956건
- 세션 전환율 5.7%, 세션당 페이지뷰 2.7, 현재 시각 이후 이벤트 없음
- 일별·채널별·시간대별 분포에서 위 패턴 확인

## 실행 후 집계 백필 (backend 디렉토리)

스크립트 마지막 NOTICE에 날짜가 채워진 명령이 출력됨

1. agg_* 재계산
  ```bash
  ./gradlew bootRun --args="--klicklab.rollup.backfill-days-on-startup=30"
  ```

2. minutes/hourly/daily/weekly_*
  ```bash
  ./gradlew bootRun --args="--aggregate=backfill --from=<시작일> --to=<오늘>"
  ```
