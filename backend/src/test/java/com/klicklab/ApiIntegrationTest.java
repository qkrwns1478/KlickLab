package com.klicklab;

import com.klicklab.common.AppClock;
import com.klicklab.rollup.RollupService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.hasItem;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.cookie;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "klicklab.jwt.secret=test-access-secret-0123456789-abcdefghij",
        "klicklab.jwt.refresh-secret=test-refresh-secret-0123456789-abcdefghij",
        "klicklab.auth.auto-approve=true",
        "klicklab.rollup.enabled=true",
        "klicklab.rollup.backfill-days-on-startup=0",
        "spring.config.import=",
})
@AutoConfigureMockMvc
@Testcontainers(disabledWithoutDocker = true)
class ApiIntegrationTest {

    static final ZoneId KST = ZoneId.of("Asia/Seoul");
    /** 고정 시각: 2026-03-15(일) 15:00 KST */
    static final ZonedDateTime NOW = ZonedDateTime.of(2026, 3, 15, 15, 0, 0, 0, KST);
    static final LocalDate TODAY = NOW.toLocalDate();
    static final LocalDate YESTERDAY = TODAY.minusDays(1);

    @Container
    @ServiceConnection
    static PostgreSQLContainer postgres = new PostgreSQLContainer(
            DockerImageName.parse("pgvector/pgvector:pg17").asCompatibleSubstituteFor("postgres"));

    @TestConfiguration
    static class FixedClockConfig {
        @Bean
        @Primary
        AppClock fixedClock() {
            return new AppClock(Clock.fixed(NOW.toInstant(), KST));
        }
    }

    @Autowired
    MockMvc mvc;
    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    RollupService rollupService;

    static String token;
    static String sdkKey;
    static boolean seeded;
    static Exception seedFailure;

    /** 컨테이너/컨텍스트는 클래스 단위로 공유되므로 데이터는 한 번만 적재 */
    @BeforeEach
    void setUp() throws Exception {
        if (seedFailure != null) {
            throw new IllegalStateException("test data setup failed", seedFailure);
        }
        if (seeded) {
            return;
        }
        try {
            seed();
            seeded = true;
        } catch (Exception e) {
            seedFailure = e;
            throw e;
        }
    }

    private void seed() throws Exception {
        mvc.perform(post("/api/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"owner@klicklab.co.kr\",\"password\":\"pw1234\"}"))
                .andExpect(status().isCreated());
        MvcResult login = mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"owner@klicklab.co.kr\",\"password\":\"pw1234\"}"))
                .andExpect(status().isOk())
                .andExpect(cookie().httpOnly("refreshToken", true))
                .andReturn();
        token = extract(login.getResponse().getContentAsString(), "accessToken");
        sdkKey = jdbc.queryForObject("SELECT sdk_key FROM users WHERE email = 'owner@klicklab.co.kr'", String.class);

        mvc.perform(post("/api/conversion-events").header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"event_name\":\"is_payment\",\"description\":\"결제\"}"))
                .andExpect(status().isCreated());

        // 오늘: c1(구매 전환, google) / c2(direct, 모바일)
        event("page_view", at(14, 35), "c1", "s1", "/", "google", "desktop", "Chrome", "Seoul", "male", 25, "");
        event("auto_click", at(14, 36), "c1", "s1", "/", "google", "desktop", "Chrome", "Seoul", "male", 25, "Buy");
        event("page_view", at(14, 37), "c1", "s1", "/cart", "google", "desktop", "Chrome", "Seoul", "male", 25, "");
        event("page_view", at(14, 39), "c1", "s1", "/checkout/success", "google", "desktop", "Chrome", "Seoul", "male", 25, "");
        event("is_payment", at(14, 39), "c1", "s1", "/checkout/success", "google", "desktop", "Chrome", "Seoul", "male", 25, "");
        event("page_view", at(14, 45), "c2", "s2", "/", "", "mobile", "Safari", "Busan", "female", 34, "");
        event("page_view", at(14, 50), "c2", "s2", "/products", "", "mobile", "Safari", "Busan", "female", 34, "");
        // 어제: c1 재방문
        event("page_view", NOW.minusDays(1).withHour(11), "c1", "s0", "/", "naver", "desktop", "Chrome", "Seoul", "male", 25, "");

        rollupService.refreshRange(YESTERDAY, TODAY);
    }

    @Test
    void rejectsMissingOrInvalidToken() throws Exception {
        mvc.perform(get("/api/stats/visitors"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.message").value("인증 토큰이 필요합니다"));
        mvc.perform(get("/api/stats/visitors").header("Authorization", "Bearer nope"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.message").value("유효하지 않은 토큰입니다"));
    }

    @Test
    void corsAllowsViteDevServerAndRejectsUnknownOrigins() throws Exception {
        String body = "{\"email\":\"owner@klicklab.co.kr\",\"password\":\"pw1234\"}";
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON).content(body)
                        .header("Origin", "http://localhost:5173"))
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:5173"))
                .andExpect(header().string("Access-Control-Allow-Credentials", "true"));
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON).content(body)
                        .header("Origin", "http://evil.example.com"))
                .andExpect(status().isForbidden());
    }

    @Test
    void loginFailsWithWrongPassword() throws Exception {
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"owner@klicklab.co.kr\",\"password\":\"wrong\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void settingsReturnsSdkKeyAsJsonString() throws Exception {
        authed(get("/api/settings/get-key"))
                .andExpect(content().string("\"" + sdkKey + "\""));
        authed(get("/api/settings/get-domain"))
                .andExpect(jsonPath("$.eventCount").value(6))
                .andExpect(jsonPath("$.lastEvent").value("2026-03-15 14:50:00"));
    }

    @Test
    void sdkRulesArePublic() throws Exception {
        mvc.perform(get("/api/sdk/rules").param("sdk_key", sdkKey))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.eventRules").isArray())
                .andExpect(jsonPath("$.eventbutton").isArray());
    }

    @Test
    void statsVisitorsAndClicks() throws Exception {
        authed(get("/api/stats/visitors"))
                .andExpect(jsonPath("$.today").value(2))
                .andExpect(jsonPath("$.yesterday").value(1))
                .andExpect(jsonPath("$.trend[0].date").value("2026-03-14"));
        authed(get("/api/stats/clicks"))
                .andExpect(jsonPath("$.today").value(1));
        authed(get("/api/stats/top-clicks"))
                .andExpect(jsonPath("$.items[0].label").value("Buy"));
        authed(get("/api/stats/click-trend").param("baseTime", "2026-03-15T06:00:00.000Z").param("period", "60"))
                .andExpect(jsonPath("$.data[0].count").value(1));
    }

    @Test
    void conversionTopPaths() throws Exception {
        authed(get("/api/stats/userpath-summary/conversion-top3")
                .param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.totalConversion").value(1))
                .andExpect(jsonPath("$.data[0].path[2]").value("/checkout/success"))
                .andExpect(jsonPath("$.data[0].conversionRate").value(100.0));
        authed(get("/api/stats/userpath-summary"))
                .andExpect(jsonPath("$.data[*].from", hasItem("/")));
        authed(get("/api/stats/sankey-paths").param("type", "url")
                .param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data[*].url_path[2]", hasItem("/checkout/success")));
    }

    @Test
    void overviewEndpoints() throws Exception {
        authed(get("/api/overview/realtime"))
                .andExpect(jsonPath("$.data.activeUsers30min").value(2))
                .andExpect(jsonPath("$.data.trend.length()").value(30));
        authed(get("/api/overview/user-stats").param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data.activeUsers").value(3))
                .andExpect(jsonPath("$.data.sessions").value(3));
        authed(get("/api/overview/traffic-stats").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data.trafficSources[*].source", hasItem("direct")));
        authed(get("/api/overview/page-stats").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data.topPages[0].page").value("/"))
                .andExpect(jsonPath("$.data.topPages[0].views").value(2));
        authed(get("/api/overview/event-stats").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data.topEvents[0].event").value("page_view"));
    }

    @Test
    void engagementEndpoints() throws Exception {
        authed(get("/api/engagement/revisit").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$[0].dau").value(2))
                .andExpect(jsonPath("$[0].wau").value(2));
        authed(get("/api/engagement/users-over-time").param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$[0].dailyUsers").value(1))
                .andExpect(jsonPath("$[1].weeklyUsers").value(2));
        authed(get("/api/engagement/overview").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.avgSessionSeconds[0].avgSessionSeconds").value(270.0));
        authed(get("/api/engagement/exit-rate").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$[0].bounce_rate").value(100.0));
        for (String path : new String[]{"page-times", "bounce-rate", "page-views", "view-counts", "click-counts",
                "event-counts", "page-stats", "visit-stats"}) {
            authed(get("/api/engagement/" + path).param("startDate", "2026-03-14").param("endDate", "2026-03-15"));
        }
        mvc.perform(get("/api/engagement/overview").header("Authorization", "Bearer " + token))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Missing startDate or endDate"));
    }

    @Test
    void acquisitionEndpoints() throws Exception {
        authed(get("/api/acquisition/funnel-conversion").param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$[0].users").value(3))
                .andExpect(jsonPath("$[2].users").value(1));
        authed(get("/api/acquisition/platform-analysis").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.device[*].type", hasItem("mobile")));
        authed(get("/api/acquisition/landing-pages").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$[0].page").value("/"));
        for (String path : new String[]{"overview", "hourly-trend", "top-channels", "channel-groups", "campaigns",
                "top-countries", "click-flow"}) {
            authed(get("/api/acquisition/" + path).param("startDate", "2026-03-14").param("endDate", "2026-03-15"));
        }
    }

    @Test
    void trafficUsersAndFunnel() throws Exception {
        for (String period : new String[]{"hourly", "daily", "weekly", "monthly"}) {
            authed(get("/api/traffic").param("period", period).param("gender", "male"))
                    .andExpect(jsonPath("$.hourlyTraffic.length()").value(24));
        }
        authed(get("/api/traffic/daily-visitors"))
                .andExpect(jsonPath("$.data[-1:].visitors", hasItem(2)));
        authed(get("/api/traffic/channel-conversion"))
                .andExpect(jsonPath("$.success").value(true));
        authed(get("/api/users/realtime-analytics").param("startDate", "2026-03-15").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.data[*].age_group", hasItem("20s")))
                .andExpect(jsonPath("$.meta.isOnlyToday").value(true));
        authed(get("/api/funnel/path/next").param("page", "/").param("from", "2026-03-15").param("to", "2026-03-15"))
                .andExpect(jsonPath("$[*].target", hasItem("/cart")));
        authed(get("/api/funnel/start-pages").param("from", "2026-03-14").param("to", "2026-03-15"))
                .andExpect(jsonPath("$[0].page_path").value("/"))
                .andExpect(jsonPath("$[0].sessions").value(3));
    }

    @Test
    void reportExports() throws Exception {
        authed(get("/api/report/kpi-report").param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(jsonPath("$.visitors.data.length()").value(2))
                .andExpect(jsonPath("$.conversions.data[1].conversions").value(1));
        authed(get("/api/report/kpi-report/md").param("startDate", "2026-03-14").param("endDate", "2026-03-15"))
                .andExpect(content().string(containsString("| date | visitors | sessions | avg_session_seconds |")));
        mvc.perform(post("/api/report/kpi-report/csv").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"visitors\":{\"category\":\"방문\",\"data\":[{\"date\":\"2026-03-15\",\"visitors\":2}]}}"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"=\"\"2026-03-15\"\"\",2")));
    }

    @Test
    void conversionEventsAndRules() throws Exception {
        authed(post("/api/rules").contentType(MediaType.APPLICATION_JSON).content("""
                {"new_event_name":"signup_done","source_event_name":"page_view","condition_type":"url",
                 "condition_parameter":"page_path","condition_value":"/signup/success"}"""), 201);
        authed(get("/api/conversion-events/available"))
                .andExpect(jsonPath("$.available[*].event_name", hasItem("signup_done")))
                .andExpect(jsonPath("$.registered", hasItem("is_payment")));
        authed(get("/api/conversion-events/stats").param("start_date", "2026-03-14").param("end_date", "2026-03-15"))
                .andExpect(jsonPath("$.byEvent[0].event_name").value("is_payment"));
    }

    // ----------------------------------------------------------------------------------------------

    private org.springframework.test.web.servlet.ResultActions authed(
            org.springframework.test.web.servlet.RequestBuilder request) throws Exception {
        return authed(request, 200);
    }

    private org.springframework.test.web.servlet.ResultActions authed(
            org.springframework.test.web.servlet.RequestBuilder request, int expectedStatus) throws Exception {
        if (request instanceof org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder b) {
            b.header("Authorization", "Bearer " + token);
        }
        return mvc.perform(request).andExpect(status().is(expectedStatus));
    }

    private static ZonedDateTime at(int hour, int minute) {
        return NOW.withHour(hour).withMinute(minute);
    }

    private void event(String name, ZonedDateTime ts, String client, String session, String page, String source,
                       String device, String browser, String city, String gender, int age, String element) {
        jdbc.update("""
                        INSERT INTO events (sdk_key, event_name, timestamp, client_id, session_id, page_path,
                                            traffic_source, device_type, browser, city, user_gender, user_age, element)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, sdkKey, name, Timestamp.from(ts.toInstant()), client, session, page, source, device,
                browser, city, gender, age, element);
    }

    private static String extract(String json, String field) {
        Matcher m = Pattern.compile("\"" + field + "\"\\s*:\\s*\"([^\"]+)\"").matcher(json);
        if (!m.find()) {
            throw new IllegalStateException(field + " not found in " + json);
        }
        return m.group(1);
    }
}
