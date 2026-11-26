-- =====================================================================
-- KlickLab 데모 클릭스트림 데이터셋 생성 스크립트
--
--  가상의 이커머스 "KlickShop"(https://shop.klicklab.dev)의 최근 4주 + 이번 주 이벤트를 생성한다.
--  * 계정      : demo@klicklab.dev / demo1234!  (승인 완료, 전환 이벤트 is_payment)
--  * 기간      : 4주 전 월요일 00:00 ~ 현재 시각 (Asia/Seoul)
--  * 규모      : 방문자 약 2만 명, 세션 약 3.3만 개, 이벤트 약 26만 건
--  * 이벤트    : page_view, auto_click, add_to_cart, is_payment, is_signup, contact_submit
--
--  데이터에 심어 둔 패턴
--  * 시간대: 점심(12시)과 저녁(20~22시) 피크, 새벽 저점 / 데스크톱은 업무 시간 비중이 높음
--  * 요일  : 주말 방문 증가, 화요일 뉴스레터(email) 발송으로 email 유입 급증
--  * 성장  : 신규 방문자가 기간 후반으로 갈수록 증가
--  * 캠페인: 최근 2~8일 전 'nov_mega_sale' (naver cpc / instagram / kakao) 신규 유입 급증
--  * 채널  : email·naver cpc·재방문 direct 는 전환 의도가 높고, instagram·youtube 는 이탈이 많음
--  * 장애  : 15일 전 모바일 결제 오류 → 해당 일 모바일 /checkout → /checkout/success 전환 0
--  * 회원  : 약 32% 가 로그인 회원(user_id 보유), 재방문 빈도가 높음
--
--  실행 (스키마는 앱 기동 시 Flyway 가 생성해 두어야 한다)
--    docker exec -i klicklab-postgres psql -U klicklab -d klicklab -v ON_ERROR_STOP=1 < seed/clickstream_seed.sql
--
--  같은 sdk_key 의 기존 이벤트/집계는 지우고 다시 만들므로 여러 번 실행해도 된다(멱등).
--  집계 테이블은 이 스크립트가 채우지 않는다. 실행 후 마지막 NOTICE 에 출력되는 명령으로
--  agg_* (RollupService) 와 minutes/hourly/daily/weekly_* (Spring Batch) 를 백필한다.
-- =====================================================================

BEGIN;

SET LOCAL TIME ZONE 'Asia/Seoul';
SELECT setseed(0.20261110);  -- 같은 날 실행하면 같은 데이터

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- 데모 계정 비밀번호(bcrypt)

-- ---------------------------------------------------------------------
-- 설정
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_cfg ON COMMIT DROP AS
SELECT 'klicklab-demo-sdk-key-0001'::varchar(64)          AS sdk_key,
       (date_trunc('week', current_date)::date - 28)      AS start_day,   -- 4주 전 월요일
       current_date                                        AS end_day,
       current_date - 8                                    AS sale_start,  -- 캠페인 기간
       current_date - 2                                    AS sale_end,
       current_date - 15                                   AS outage_day,  -- 모바일 결제 장애
       'https://shop.klicklab.dev'::text                   AS origin,
       30000                                               AS client_count;

-- ---------------------------------------------------------------------
-- 헬퍼 함수 (세션 한정)
-- ---------------------------------------------------------------------
-- 가중치 랜덤 선택: r ∈ [0, 1)
CREATE FUNCTION pg_temp.pick(labels text[], weights numeric[], r float8) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT labels[i]
    FROM (SELECT i, sum(weights[i]) OVER (ORDER BY i) / sum(weights[i]) OVER () AS cum
          FROM generate_subscripts(weights, 1) i) t
    WHERE r::numeric < cum
    ORDER BY i
    LIMIT 1
$$;

-- 표준정규분포 (Box-Muller)
CREATE FUNCTION pg_temp.gauss() RETURNS float8
LANGUAGE sql VOLATILE AS $$
    SELECT sqrt(-2 * ln(1 - random())) * cos(2 * pi() * random())
$$;

-- ---------------------------------------------------------------------
-- 기존 데이터 정리 (데모 sdk_key 한정)
-- ---------------------------------------------------------------------
DO $$
DECLARE
    k text := (SELECT sdk_key FROM seed_cfg);
    t text;
    g text;
BEGIN
    FOREACH t IN ARRAY ARRAY['events', 'conversion_events', 'event_rules', 'event_button',
        'agg_user_session_daily', 'agg_user_session_hourly', 'agg_daily_users', 'agg_page_daily',
        'agg_event_daily', 'agg_event_page_daily', 'agg_traffic_hourly', 'agg_funnel_links_daily',
        'agg_first_pages_daily', 'agg_sankey_paths_daily'] LOOP
        EXECUTE format('DELETE FROM %I WHERE sdk_key = $1', t) USING k;
    END LOOP;
    FOREACH g IN ARRAY ARRAY['minutes', 'hourly', 'daily', 'weekly'] LOOP
        FOREACH t IN ARRAY ARRAY['metrics', 'click_summary', 'top_elements', 'user_distribution', 'page_stats'] LOOP
            EXECUTE format('DELETE FROM %I WHERE sdk_key = $1', g || '_' || t) USING k;
        END LOOP;
    END LOOP;
END $$;

-- 집계 이력을 지워 앱 기동 시 백필 대상이 되도록 한다
DELETE FROM rollup_runs r USING seed_cfg c WHERE r.summary_date BETWEEN c.start_day AND c.end_day;

-- ---------------------------------------------------------------------
-- 계정 / 설정
-- ---------------------------------------------------------------------
INSERT INTO users (email, password_hash, sdk_key, is_approved, event, domain)
SELECT 'demo@klicklab.dev', crypt('demo1234!', gen_salt('bf', 10)), sdk_key, TRUE, 'is_payment', 'shop.klicklab.dev'
FROM seed_cfg
ON CONFLICT (email) DO UPDATE
    SET password_hash = EXCLUDED.password_hash, sdk_key = EXCLUDED.sdk_key, is_approved = TRUE,
        event = EXCLUDED.event, domain = EXCLUDED.domain, updated_at = now();

INSERT INTO conversion_events (sdk_key, event_name, description, is_active)
SELECT c.sdk_key, v.event_name, v.description, v.is_active
FROM seed_cfg c, (VALUES
    ('is_payment',     '결제 완료',     1),
    ('is_signup',      '회원가입 완료', 1),
    ('add_to_cart',    '장바구니 담기', 0),
    ('contact_submit', '문의 접수',     0)
) v(event_name, description, is_active);

INSERT INTO event_button (config_id, sdk_key, event_name, css_selector, description)
SELECT gen_random_uuid(), c.sdk_key, v.event_name, v.css_selector, v.description
FROM seed_cfg c, (VALUES
    ('add_to_cart',    'button.btn-add-cart',   '상품 상세 장바구니 추가 버튼'),
    ('contact_submit', 'form#contact button[type=submit]', '1:1 문의 등록 버튼')
) v(event_name, css_selector, description);

-- ---------------------------------------------------------------------
-- 사이트 구조: 페이지 / 상품 / 페이지 전이 / 채널
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_pages (
    page         text PRIMARY KEY,   -- '/products/:id' 는 상품 상세 템플릿
    title        text    NOT NULL,
    dwell_median float8  NOT NULL,   -- 체류 시간 중앙값(초)
    click_mean   float8  NOT NULL,   -- 페이지뷰당 평균 클릭 수 (이동 클릭 제외)
    elements     text[]  NOT NULL    -- 앞쪽일수록 많이 클릭됨
) ON COMMIT DROP;

INSERT INTO seed_pages VALUES
('/',                 '홈 | KlickShop',          12, 1.4, ARRAY['메인 배너', '추천 상품 카드', '검색창', '카테고리 메뉴', '이벤트 배너', '로그인 버튼']),
('/products',         '전체 상품 | KlickShop',   25, 2.0, ARRAY['상품 카드', '검색 필터', '정렬 옵션', '카테고리 탭', '다음 페이지', '위시리스트']),
('/products/:id',     '상품 상세 | KlickShop',   45, 2.3, ARRAY['상품 이미지', '옵션 선택', '리뷰 보기', '장바구니 추가', '위시리스트', '바로 구매', '상품 문의']),
('/cart',             '장바구니 | KlickShop',    30, 1.5, ARRAY['수량 변경', '쿠폰 적용', '상품 삭제', '쇼핑 계속하기', '주문하기']),
('/checkout',         '주문/결제 | KlickShop',   70, 2.2, ARRAY['배송지 입력', '결제수단 선택', '약관 동의', '쿠폰 적용', '결제하기']),
('/checkout/success', '주문 완료 | KlickShop',   15, 0.6, ARRAY['주문 상세 보기', '쇼핑 계속하기']),
('/login',            '로그인 | KlickShop',      20, 1.0, ARRAY['로그인 버튼', '카카오 로그인', '네이버 로그인', '비밀번호 찾기']),
('/signup',           '회원가입 | KlickShop',    60, 1.6, ARRAY['약관 동의', '이메일 인증', '가입하기']),
('/signup/success',   '가입 완료 | KlickShop',    8, 0.4, ARRAY['쇼핑 시작하기', '쿠폰함']),
('/mypage',           '마이페이지 | KlickShop',  15, 1.0, ARRAY['주문 내역', '쿠폰함', '회원정보 수정', '위시리스트']),
('/orders',           '주문 내역 | KlickShop',   25, 1.2, ARRAY['배송 조회', '주문 상세 보기', '리뷰 작성']),
('/wishlist',         '위시리스트 | KlickShop',  20, 1.0, ARRAY['상품 카드', '장바구니 추가', '삭제']),
('/faq',              'FAQ | KlickShop',         50, 1.8, ARRAY['FAQ 항목', '1:1 문의']),
('/contact',          '1:1 문의 | KlickShop',    80, 1.2, ARRAY['문의 유형 선택', '파일 첨부', '문의 등록']),
('/contact/success',  '문의 완료 | KlickShop',    6, 0.2, ARRAY['홈으로']);

-- 다음 페이지로 이동할 때 발생하는 클릭
CREATE TEMP TABLE seed_nav (from_page text, to_page text, element text, PRIMARY KEY (from_page, to_page)) ON COMMIT DROP;
INSERT INTO seed_nav VALUES
('/', '/products', '카테고리 메뉴'), ('/', '/products/:id', '추천 상품 카드'), ('/', '/login', '로그인 버튼'),
('/', '/cart', '장바구니 아이콘'), ('/', '/mypage', '마이페이지 아이콘'),
('/products', '/products/:id', '상품 카드'), ('/products/:id', '/cart', '장바구니 추가'),
('/products/:id', '/products/:id', '연관 상품 카드'), ('/products/:id', '/wishlist', '위시리스트'),
('/cart', '/checkout', '주문하기'), ('/cart', '/products', '쇼핑 계속하기'),
('/checkout', '/checkout/success', '결제하기'), ('/checkout/success', '/orders', '주문 상세 보기'),
('/login', '/signup', '회원가입 링크'), ('/signup', '/signup/success', '가입하기'),
('/signup/success', '/products', '쇼핑 시작하기'), ('/mypage', '/orders', '주문 내역'),
('/wishlist', '/products/:id', '상품 카드'), ('/wishlist', '/cart', '장바구니 추가'),
('/faq', '/contact', '1:1 문의'), ('/contact', '/contact/success', '문의 등록');

CREATE TEMP TABLE seed_products ON COMMIT DROP AS
SELECT id, (12900 + ((id * 37) % 17) * 5000)::int AS price
FROM generate_series(1, 24) id;

-- 페이지 전이 가중치: 전환 의도 수준(낮음/중간/높음)별
CREATE TEMP TABLE seed_trans_raw (ord serial, from_page text, to_page text, w0 int, w1 int, w2 int) ON COMMIT DROP;
INSERT INTO seed_trans_raw (from_page, to_page, w0, w1, w2) VALUES
('/', '/products', 30, 34, 36), ('/', '/products/:id', 18, 22, 26), ('/', '/login', 3, 5, 6),
('/', '/signup', 3, 3, 3), ('/', '/mypage', 1, 3, 5), ('/', '/faq', 2, 2, 1), ('/', '/wishlist', 1, 2, 3),
('/', '/cart', 1, 2, 4), ('/', 'EXIT', 42, 27, 16),
('/products', '/products/:id', 38, 50, 58), ('/products', '/', 6, 5, 4), ('/products', '/cart', 1, 3, 5),
('/products', '/wishlist', 1, 2, 2), ('/products', 'EXIT', 50, 38, 30),
('/products/:id', '/products/:id', 18, 22, 22), ('/products/:id', '/products', 12, 13, 12),
('/products/:id', '/cart', 3, 8, 16), ('/products/:id', '/wishlist', 3, 4, 5), ('/products/:id', '/', 4, 4, 3),
('/products/:id', '/login', 1, 2, 2), ('/products/:id', 'EXIT', 58, 44, 34),
('/cart', '/checkout', 16, 30, 46), ('/cart', '/products', 10, 10, 8), ('/cart', '/products/:id', 10, 9, 7),
('/cart', '/login', 4, 5, 4), ('/cart', '/', 3, 3, 2), ('/cart', 'EXIT', 53, 35, 21),
('/checkout', '/checkout/success', 40, 58, 74), ('/checkout', '/cart', 12, 10, 7), ('/checkout', 'EXIT', 48, 32, 19),
('/checkout/success', '/orders', 20, 22, 25), ('/checkout/success', '/', 12, 12, 12),
('/checkout/success', '/products', 8, 10, 12), ('/checkout/success', 'EXIT', 60, 56, 51),
('/login', '/', 30, 30, 30), ('/login', '/mypage', 15, 17, 18), ('/login', '/cart', 8, 12, 16),
('/login', '/signup', 10, 8, 5), ('/login', 'EXIT', 37, 33, 31),
('/signup', '/signup/success', 30, 45, 60), ('/signup', '/login', 8, 6, 4), ('/signup', 'EXIT', 62, 49, 36),
('/signup/success', '/', 40, 40, 40), ('/signup/success', '/products', 25, 28, 30), ('/signup/success', 'EXIT', 35, 32, 30),
('/mypage', '/orders', 30, 32, 34), ('/mypage', '/wishlist', 15, 16, 17), ('/mypage', '/', 12, 12, 12),
('/mypage', '/contact', 4, 4, 3), ('/mypage', 'EXIT', 39, 36, 34),
('/orders', '/mypage', 15, 15, 15), ('/orders', '/products', 10, 12, 14), ('/orders', '/contact', 5, 4, 3),
('/orders', '/faq', 4, 3, 2), ('/orders', 'EXIT', 66, 66, 66),
('/wishlist', '/products/:id', 30, 35, 40), ('/wishlist', '/cart', 8, 12, 16), ('/wishlist', 'EXIT', 62, 53, 44),
('/faq', '/contact', 15, 15, 15), ('/faq', '/', 20, 20, 20), ('/faq', '/products', 10, 10, 10), ('/faq', 'EXIT', 55, 55, 55),
('/contact', '/contact/success', 35, 45, 55), ('/contact', '/faq', 8, 8, 8), ('/contact', 'EXIT', 57, 47, 37),
('/contact/success', '/', 30, 30, 30), ('/contact/success', 'EXIT', 70, 70, 70);

-- 누적 확률 구간 [lo, hi)
CREATE TEMP TABLE seed_trans ON COMMIT DROP AS
SELECT from_page, to_page, lvl,
    COALESCE(sum(w) OVER (PARTITION BY from_page, lvl ORDER BY ord
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)::numeric
        / sum(w) OVER (PARTITION BY from_page, lvl) AS lo,
    sum(w) OVER (PARTITION BY from_page, lvl ORDER BY ord)::numeric
        / sum(w) OVER (PARTITION BY from_page, lvl) AS hi
FROM (SELECT t.ord, t.from_page, t.to_page, l.lvl, (ARRAY[t.w0, t.w1, t.w2])[l.lvl + 1] AS w
      FROM seed_trans_raw t CROSS JOIN generate_series(0, 2) l(lvl)) s
WHERE w > 0;
CREATE INDEX ON seed_trans (from_page, lvl);

-- 유입 채널: 전환 의도 / 랜딩 페이지 분포
CREATE TEMP TABLE seed_channels (
    channel      text PRIMARY KEY,
    source       text,
    medium       text,
    campaign     text,
    referrer     text,
    intent       float8,
    landing      text[],
    landing_w    numeric[]
) ON COMMIT DROP;

INSERT INTO seed_channels VALUES
('direct',         'direct',    'none',     '',                  '',                              0.62, ARRAY['/', '/cart', '/mypage', '/orders'],            ARRAY[85, 5, 5, 5]),
('google',         'google',    'organic',  '',                  'https://www.google.com/',       0.52, ARRAY['/', '/products/:id', '/products', '/faq'],     ARRAY[45, 35, 15, 5]),
('naver',          'naver',     'organic',  '',                  'https://search.naver.com/',     0.54, ARRAY['/', '/products/:id', '/products', '/faq'],     ARRAY[45, 35, 15, 5]),
('daum',           'daum',      'organic',  '',                  'https://search.daum.net/',      0.50, ARRAY['/', '/products/:id', '/products'],             ARRAY[50, 35, 15]),
('naver_cpc',      'naver',     'cpc',      'brand_search',      'https://search.naver.com/',     0.70, ARRAY['/products/:id', '/products', '/'],             ARRAY[55, 30, 15]),
('kakao',          'kakao',     'social',   '',                  'https://talk.kakao.com/',       0.45, ARRAY['/', '/products/:id'],                          ARRAY[50, 50]),
('instagram',      'instagram', 'social',   '',                  'https://l.instagram.com/',      0.30, ARRAY['/products/:id', '/'],                          ARRAY[55, 45]),
('facebook_cpc',   'facebook',  'cpc',      'retargeting',       'https://l.facebook.com/',       0.38, ARRAY['/products/:id', '/cart'],                      ARRAY[80, 20]),
('youtube',        'youtube',   'referral', '',                  'https://www.youtube.com/',      0.25, ARRAY['/products/:id', '/'],                          ARRAY[60, 40]),
('email',          'newsletter','email',    'weekly_newsletter', '',                              0.80, ARRAY['/products', '/products/:id', '/'],             ARRAY[45, 35, 20]),
('sale_naver',     'naver',     'cpc',      'nov_mega_sale',     'https://search.naver.com/',     0.62, ARRAY['/products', '/products/:id'],                  ARRAY[60, 40]),
('sale_instagram', 'instagram', 'cpc',      'nov_mega_sale',     'https://l.instagram.com/',      0.40, ARRAY['/products/:id', '/products'],                  ARRAY[70, 30]),
('sale_kakao',     'kakao',     'push',     'nov_mega_sale',     'https://talk.kakao.com/',       0.50, ARRAY['/products', '/'],                              ARRAY[70, 30]);

-- ---------------------------------------------------------------------
-- 방문자
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_clients ON COMMIT DROP AS
WITH r AS (
    SELECT n, random() AS r_gender, random() AS r_age, random() AS r_age2, random() AS r_city,
        random() AS r_dev, random() AS r_os, random() AS r_br, random() AS r_member,
        random() AS r_kind, random() AS r_first, random() AS r_visits
    FROM generate_series(1, (SELECT client_count FROM seed_cfg)) n
), a AS (
    SELECT r.*,
        CASE WHEN r_kind < 0.28 THEN 'existing' WHEN r_kind < 0.42 THEN 'sale' ELSE 'organic' END AS kind,
        CASE WHEN r_gender < 0.52 THEN 'female' WHEN r_gender < 0.95 THEN 'male' END AS gender,
        CASE WHEN r_age < 0.07 THEN 14 + floor(r_age2 * 6)
             WHEN r_age < 0.38 THEN 20 + floor(r_age2 * 10)
             WHEN r_age < 0.66 THEN 30 + floor(r_age2 * 10)
             WHEN r_age < 0.84 THEN 40 + floor(r_age2 * 10)
             WHEN r_age < 0.94 THEN 50 + floor(r_age2 * 10)
             ELSE 60 + floor(r_age2 * 13) END::smallint AS age0,
        pg_temp.pick(
            ARRAY['Seoul', 'Gyeonggi-do', 'Busan', 'Incheon', 'Daegu', 'Daejeon', 'Gwangju', 'Ulsan', 'Sejong',
                  'Gangwon-do', 'Chungcheongbuk-do', 'Chungcheongnam-do', 'Jeollabuk-do', 'Jeollanam-do',
                  'Gyeongsangbuk-do', 'Gyeongsangnam-do', 'Jeju-do'],
            ARRAY[340, 260, 70, 60, 45, 30, 25, 20, 10, 20, 18, 22, 17, 15, 20, 18, 13], r_city) AS city
    FROM r
), d AS (
    SELECT a.*,
        CASE WHEN gender IS NULL THEN NULL ELSE age0 END AS age,
        pg_temp.pick(ARRAY['mobile', 'desktop', 'tablet'],
            CASE WHEN age0 < 30 THEN ARRAY[74, 22, 4] WHEN age0 < 50 THEN ARRAY[60, 34, 6] ELSE ARRAY[55, 37, 8] END,
            r_dev) AS device_type
    FROM a
), o AS (
    SELECT d.*,
        CASE device_type
            WHEN 'mobile'  THEN pg_temp.pick(ARRAY['iOS', 'Android'], ARRAY[45, 55], r_os)
            WHEN 'tablet'  THEN pg_temp.pick(ARRAY['iPadOS', 'Android'], ARRAY[60, 40], r_os)
            ELSE pg_temp.pick(ARRAY['Windows', 'macOS', 'Linux'], ARRAY[72, 25, 3], r_os) END AS device_os
    FROM d
)
SELECT n,
    'cid_' || lpad(to_hex((n::bigint * 2654435761) % 4294967296), 8, '0') AS client_id,
    CASE WHEN r_member < 0.32 THEN 'u_' || (100000 + n) END AS user_id,
    kind, gender, age, city, device_type, device_os,
    CASE device_os
        WHEN 'iOS'     THEN pg_temp.pick(ARRAY['Safari', 'Chrome', 'Whale'], ARRAY[80, 15, 5], r_br)
        WHEN 'iPadOS'  THEN pg_temp.pick(ARRAY['Safari', 'Chrome'], ARRAY[85, 15], r_br)
        WHEN 'Android' THEN pg_temp.pick(ARRAY['Chrome', 'Samsung Internet', 'Whale'], ARRAY[60, 32, 8], r_br)
        WHEN 'Windows' THEN pg_temp.pick(ARRAY['Chrome', 'Edge', 'Whale', 'Firefox'], ARRAY[68, 18, 11, 3], r_br)
        WHEN 'macOS'   THEN pg_temp.pick(ARRAY['Safari', 'Chrome', 'Whale'], ARRAY[50, 45, 5], r_br)
        ELSE pg_temp.pick(ARRAY['Chrome', 'Firefox'], ARRAY[75, 25], r_br) END AS browser,
    CASE kind
        WHEN 'existing' THEN c.start_day - 1 - floor(r_first * 45)::int
        WHEN 'sale'     THEN c.sale_start + floor(r_first * (c.sale_end - c.sale_start + 1))::int
        ELSE c.start_day + floor(power(r_first, 0.8) * (c.end_day - c.start_day + 1))::int END AS first_day,
    -- 방문 횟수 (회원·기존 방문자일수록 많음)
    least(40, 1 + floor(-ln(1 - r_visits)
        * CASE WHEN r_member < 0.32 THEN 4.0 ELSE 0.7 END
        * CASE kind WHEN 'existing' THEN 1.6 WHEN 'sale' THEN 0.7 ELSE 1.0 END))::int AS visit_count,
    CASE WHEN r_member < 0.32 THEN 4.0 ELSE 7.0 END AS gap_mean
FROM o, seed_cfg c;

-- ---------------------------------------------------------------------
-- 세션
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_visits ON COMMIT DROP AS
SELECT v.n, v.k, v.first_day + (sum(v.gap) OVER (PARTITION BY v.n ORDER BY v.k))::int AS day
FROM (
    SELECT c.n, g.k, c.first_day,
        CASE WHEN g.k = 1 THEN 0 ELSE ceil(-ln(1 - random()) * c.gap_mean) END AS gap
    FROM seed_clients c
    CROSS JOIN LATERAL generate_series(1, c.visit_count) g(k)
) v;

CREATE TEMP TABLE seed_sessions ON COMMIT DROP AS
WITH v AS (
    -- 기간 내 방문만, 요일별 방문 확률 적용 (주말 증가)
    SELECT v.*, c.kind, c.user_id, c.device_type,
        (extract(isodow FROM v.day)::int) AS dow
    FROM seed_visits v
    JOIN seed_clients c USING (n)
    CROSS JOIN seed_cfg cfg
    WHERE v.day BETWEEN cfg.start_day AND cfg.end_day
      AND random() < (ARRAY[0.84, 0.80, 0.80, 0.82, 0.88, 1.00, 0.97])[extract(isodow FROM v.day)::int]
), ch AS (
    SELECT v.*,
        CASE
            WHEN v.kind = 'sale' AND v.k = 1
                THEN pg_temp.pick(ARRAY['sale_naver', 'sale_instagram', 'sale_kakao'], ARRAY[55, 30, 15], random())
            WHEN v.k > 1 AND random() < 0.42 THEN 'direct'
            ELSE pg_temp.pick(
                ARRAY['direct', 'google', 'naver', 'daum', 'naver_cpc', 'kakao', 'instagram', 'facebook_cpc', 'youtube', 'email'],
                ARRAY[22, 17, 21, 3, 7, 7, 9, 3, 5, CASE WHEN v.dow = 2 THEN 16 ELSE 3 END],
                random())
        END AS channel,
        pg_temp.pick(ARRAY['0','1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22','23'],
            CASE WHEN v.device_type = 'desktop'
                 THEN ARRAY[1.0,0.5,0.3,0.2,0.2,0.3,0.6,1.2,2.6,4.6,5.6,5.8,5.6,5.8,5.6,5.4,5.4,5.0,4.0,3.6,3.8,3.8,3.0,1.8]
                 ELSE ARRAY[2.4,1.4,0.8,0.4,0.3,0.4,0.8,1.8,2.8,3.0,3.4,3.8,5.6,4.8,3.8,3.8,4.0,4.4,5.0,5.8,6.8,7.4,7.0,4.8]
            END::numeric[], random())::int AS hour
    FROM v
)
SELECT row_number() OVER (ORDER BY ch.day, ch.hour, ch.n, ch.k) AS sid,
    ch.n, ch.k, ch.day, ch.channel,
    ch.day + make_interval(hours => ch.hour, secs => floor(random() * 3600)) AS started_at,
    -- 전환 의도 → 페이지 전이 수준
    CASE WHEN i.intent < 0.42 THEN 0 WHEN i.intent < 0.66 THEN 1 ELSE 2 END AS lvl,
    pg_temp.pick(sc.landing, sc.landing_w, random()) AS landing,
    1 + floor(24 * power(random(), 1.5))::int AS focus_product
FROM ch
JOIN seed_channels sc ON sc.channel = ch.channel
CROSS JOIN seed_cfg cfg
CROSS JOIN LATERAL (
    SELECT sc.intent
        + CASE WHEN ch.user_id IS NOT NULL THEN 0.12 ELSE 0 END
        + CASE WHEN ch.device_type = 'mobile' THEN -0.04 ELSE 0 END
        + CASE WHEN ch.day BETWEEN cfg.sale_start AND cfg.sale_end THEN 0.06 ELSE 0 END
        + 0.14 * pg_temp.gauss() AS intent
) i;

-- ---------------------------------------------------------------------
-- 세션별 페이지 이동 (마르코프 체인)
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_walk ON COMMIT DROP AS
WITH RECURSIVE walk AS (
    SELECT sid, 1 AS step, landing AS page, lvl, random() AS r
    FROM seed_sessions
    UNION ALL
    SELECT w.sid, w.step + 1, t.to_page, w.lvl, random()
    FROM walk w
    JOIN seed_trans t ON t.from_page = w.page AND t.lvl = w.lvl AND w.r::numeric >= t.lo AND w.r::numeric < t.hi
    WHERE t.to_page <> 'EXIT' AND w.step < 30
)
SELECT sid, step, page FROM walk;

-- 장애: 해당 일 모바일 세션은 결제 완료 페이지에 도달하지 못함
DELETE FROM seed_walk w
USING (
    SELECT w2.sid, min(w2.step) AS cut
    FROM seed_walk w2
    JOIN seed_sessions s ON s.sid = w2.sid
    JOIN seed_clients c ON c.n = s.n
    CROSS JOIN seed_cfg cfg
    WHERE w2.page = '/checkout/success' AND s.day = cfg.outage_day AND c.device_type = 'mobile'
    GROUP BY w2.sid
) x
WHERE w.sid = x.sid AND w.step >= x.cut;

-- 페이지별 실제 경로·체류 시간·시각
CREATE TEMP TABLE seed_steps ON COMMIT DROP AS
WITH p AS (
    SELECT w.sid, w.step, w.page,
        CASE WHEN w.page = '/products/:id'
             THEN CASE WHEN random() < 0.5 THEN s.focus_product ELSE 1 + floor(24 * power(random(), 1.6))::int END
        END AS product_id,
        least(900, greatest(2, pg.dwell_median * exp(0.7 * pg_temp.gauss()))) AS dwell,
        least(8, floor(-ln(1 - random()) * pg.click_mean))::int AS click_n
    FROM seed_walk w
    JOIN seed_sessions s ON s.sid = w.sid
    JOIN seed_pages pg ON pg.page = w.page
)
SELECT p.*,
    CASE WHEN p.product_id IS NULL THEN p.page ELSE '/products/' || p.product_id END AS page_path,
    s.started_at + make_interval(secs =>
        COALESCE(sum(p.dwell + 1) OVER (PARTITION BY p.sid ORDER BY p.step
                                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)) AS ts,
    lead(p.page) OVER (PARTITION BY p.sid ORDER BY p.step) AS next_page
FROM p
JOIN seed_sessions s ON s.sid = p.sid;

ALTER TABLE seed_steps ADD COLUMN prev_path text, ADD COLUMN next_ts timestamptz;
UPDATE seed_steps s
SET prev_path = x.prev_path, next_ts = x.next_ts
FROM (SELECT sid, step,
          lag(page_path) OVER (PARTITION BY sid ORDER BY step) AS prev_path,
          lead(ts) OVER (PARTITION BY sid ORDER BY step) AS next_ts
      FROM seed_steps) x
WHERE x.sid = s.sid AND x.step = s.step;

-- ---------------------------------------------------------------------
-- 이벤트 조립
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_events ON COMMIT DROP AS
-- 페이지뷰
SELECT st.sid, st.ts, 0 AS ord, 'page_view'::text AS event_name, st.page_path,
    CASE WHEN st.step = 1 THEN sc.referrer ELSE cfg.origin || st.prev_path END AS referrer,
    ''::text AS element, round(st.dwell::numeric, 1)::float8 AS time_on_page,
    CASE WHEN st.product_id IS NOT NULL THEN jsonb_build_object('product_id', st.product_id) END AS properties
FROM seed_steps st
JOIN seed_sessions s ON s.sid = st.sid
JOIN seed_channels sc ON sc.channel = s.channel
CROSS JOIN seed_cfg cfg
UNION ALL
-- 페이지 내 클릭
SELECT st.sid, st.ts + make_interval(secs => (0.05 + 0.85 * random()) * st.dwell), 1, 'auto_click', st.page_path,
    '', pg.elements[1 + floor(cardinality(pg.elements) * power(random(), 1.7))::int], NULL,
    jsonb_build_object('tag', 'button')
FROM seed_steps st
JOIN seed_pages pg ON pg.page = st.page
CROSS JOIN LATERAL generate_series(1, st.click_n) g
WHERE st.click_n > 0
UNION ALL
-- 다음 페이지로 이동하는 클릭
SELECT st.sid, st.next_ts - interval '800 milliseconds', 1, 'auto_click', st.page_path,
    '', nv.element, NULL, jsonb_build_object('tag', 'a')
FROM seed_steps st
JOIN seed_nav nv ON nv.from_page = st.page AND nv.to_page = st.next_page
UNION ALL
-- 장바구니 담기
SELECT st.sid, st.next_ts - interval '500 milliseconds', 2, 'add_to_cart', st.page_path,
    '', '장바구니 추가', NULL,
    jsonb_build_object('product_id', st.product_id, 'value', pr.price, 'quantity', 1, 'currency', 'KRW')
FROM seed_steps st
JOIN seed_products pr ON pr.id = st.product_id
WHERE st.page = '/products/:id' AND st.next_page = '/cart'
UNION ALL
-- 결제 완료
SELECT st.sid, st.ts + interval '300 milliseconds', 2, 'is_payment', st.page_path,
    '', '', NULL,
    jsonb_build_object('order_id', 'ORD-' || to_char(st.ts, 'YYYYMMDD') || '-' || lpad(st.sid::text, 6, '0'),
        'value', o.value, 'currency', 'KRW', 'items', o.items)
FROM seed_steps st
JOIN seed_sessions s ON s.sid = st.sid
JOIN seed_products pr ON pr.id = s.focus_product
CROSS JOIN LATERAL (
    SELECT q.items,
        (round((pr.price * q.items * (0.9 + 0.3 * random())) / 100) * 100
            + CASE WHEN pr.price * q.items < 50000 THEN 3000 ELSE 0 END)::int AS value
    FROM (SELECT CASE WHEN random() < 0.65 THEN 1 WHEN random() < 0.7 THEN 2 ELSE 3 END AS items) q
) o
WHERE st.page = '/checkout/success'
UNION ALL
-- 회원가입 / 문의 접수
SELECT st.sid, st.ts + interval '300 milliseconds', 2,
    CASE st.page WHEN '/signup/success' THEN 'is_signup' ELSE 'contact_submit' END, st.page_path,
    '', '', NULL,
    CASE st.page WHEN '/signup/success' THEN jsonb_build_object('method', CASE WHEN random() < 0.6 THEN 'kakao' ELSE 'email' END)
                 ELSE jsonb_build_object('category', (ARRAY['배송', '교환/반품', '결제', '상품'])[1 + floor(random() * 4)::int]) END
FROM seed_steps st
WHERE st.page IN ('/signup/success', '/contact/success');

-- ---------------------------------------------------------------------
-- events 적재 (현재 시각 이후 이벤트 제외, 시간순)
-- ---------------------------------------------------------------------
INSERT INTO events (sdk_key, event_name, timestamp, client_id, user_id, session_id, page_path, page_title,
                    referrer, traffic_source, traffic_medium, traffic_campaign, device_type, device_os, browser,
                    city, user_gender, user_age, element, time_on_page_seconds, properties)
SELECT cfg.sdk_key, e.event_name, e.ts, c.client_id, c.user_id, 'sess_' || lpad(s.sid::text, 7, '0'), e.page_path,
    pg.title, e.referrer, sc.source, sc.medium, sc.campaign, c.device_type, c.device_os, c.browser,
    c.city, c.gender, c.age, COALESCE(e.element, ''), e.time_on_page, e.properties
FROM seed_events e
JOIN seed_sessions s ON s.sid = e.sid
JOIN seed_clients c ON c.n = s.n
JOIN seed_channels sc ON sc.channel = s.channel
LEFT JOIN seed_pages pg ON pg.page = CASE WHEN e.page_path LIKE '/products/%' THEN '/products/:id' ELSE e.page_path END
CROSS JOIN seed_cfg cfg
WHERE e.ts <= now()
ORDER BY e.ts, e.ord;

-- ---------------------------------------------------------------------
-- 결과 요약 + 집계 백필 명령
-- ---------------------------------------------------------------------
DO $$
DECLARE
    cfg  seed_cfg%ROWTYPE;
    r    record;
BEGIN
    SELECT * INTO cfg FROM seed_cfg;
    SELECT count(*) AS events,
           count(DISTINCT session_id) AS sessions,
           count(DISTINCT client_id) AS clients,
           count(*) FILTER (WHERE event_name = 'page_view') AS page_views,
           count(*) FILTER (WHERE event_name = 'auto_click') AS clicks,
           count(*) FILTER (WHERE event_name = 'is_payment') AS payments,
           COALESCE(sum((properties ->> 'value')::numeric) FILTER (WHERE event_name = 'is_payment'), 0) AS revenue
    INTO r
    FROM events WHERE sdk_key = cfg.sdk_key;

    RAISE NOTICE '데모 데이터 생성 완료: % ~ % (sdk_key=%)', cfg.start_day, cfg.end_day, cfg.sdk_key;
    RAISE NOTICE '  이벤트 %건 / 세션 %개 / 방문자 %명 / 페이지뷰 %건 / 클릭 %건 / 결제 %건 (매출 %원)',
        r.events, r.sessions, r.clients, r.page_views, r.clicks, r.payments, r.revenue;
    RAISE NOTICE '로그인: demo@klicklab.dev / demo1234!';
    RAISE NOTICE '집계 백필 (backend 디렉토리에서):';
    RAISE NOTICE '  1) agg_*        : ./gradlew bootRun --args="--klicklab.rollup.backfill-days-on-startup=%"  (기동 로그의 Rollup backfill 완료 확인)',
        cfg.end_day - cfg.start_day + 1;
    RAISE NOTICE '  2) 시간 단위 집계: ./gradlew bootRun --args="--aggregate=backfill --from=% --to=%"',
        cfg.start_day, cfg.end_day;
END $$;

COMMIT;

ANALYZE events;
