package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(properties = {
        "klicklab.jwt.secret=test-access-secret-0123456789-abcdefghij",
        "klicklab.jwt.refresh-secret=test-refresh-secret-0123456789-abcdefghij",
        "klicklab.rollup.enabled=false",
        "klicklab.aggregation.enabled=false",
        "spring.config.import=",
})
@Testcontainers(disabledWithoutDocker = true)
class AggregationJobIntegrationTest {

    static final ZoneId KST = ZoneId.of("Asia/Seoul");
    static final String SDK = "sdk-agg";
    static final LocalDate DAY = LocalDate.of(2026, 3, 15);
    /** 고정 시각: 2026-03-16(월) 01:00 KST */
    static final ZonedDateTime NOW = DAY.plusDays(1).atTime(1, 0).atZone(KST);

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
    AggregationJobLauncher launcher;
    @Autowired
    JdbcTemplate jdbc;

    static boolean seeded;

    @BeforeEach
    void seed() {
        if (seeded) {
            return;
        }
        // 전날 방문 → c1 은 기존 방문자
        event("page_view", DAY.minusDays(1).atTime(10, 0), "c1", "s0", "/", "male", 25, "desktop", "");
        // [14:00, 14:10)
        event("page_view", DAY.atTime(14, 1), "c1", "s1", "/", "male", 25, "desktop", "");
        event("auto_click", DAY.atTime(14, 2), "c1", "s1", "/", "male", 25, "desktop", "Buy");
        event("page_view", DAY.atTime(14, 5), "c1", "s1", "/cart", "male", 25, "desktop", "");
        event("page_view", DAY.atTime(14, 3), "c2", "s2", "/", "female", 34, "mobile", "");
        event("auto_click", DAY.atTime(14, 4), "c2", "s2", "/", "female", 34, "mobile", "Menu");
        event("auto_click", DAY.atTime(14, 6), "c2", "s2", "/", "female", 34, "mobile", "Menu");
        // [14:10, 14:20)
        event("page_view", DAY.atTime(14, 12), "c2", "s2", "/cart", "female", 34, "mobile", "");
        event("page_view", DAY.atTime(14, 15), "c3", "s3", "/", "male", 41, "desktop", "");
        event("auto_click", DAY.atTime(14, 16), "c3", "s3", "/", "male", 41, "desktop", "Menu");
        // 구간 경계(14:20) 이벤트는 다음 구간에만 포함
        event("auto_click", DAY.atTime(14, 20), "c3", "s3", "/", "male", 41, "desktop", "Menu");

        launcher.run(Granularity.MINUTES, DAY.atTime(14, 0));
        launcher.run(Granularity.MINUTES, DAY.atTime(14, 10));
        launcher.run(Granularity.MINUTES, DAY.atTime(14, 20));
        launcher.run(Granularity.HOURLY, DAY.atTime(14, 0));
        launcher.run(Granularity.DAILY, DAY.atStartOfDay());
        launcher.run(Granularity.WEEKLY, DAY.atStartOfDay());
        seeded = true;
    }

    @Test
    void minutesMetricsSplitNewAndExistingVisitors() {
        Map<String, Object> first = metrics("minutes_metrics", "date_time", ts(14, 0));
        assertThat(first).containsEntry("clicks", 3L).containsEntry("visitors", 2L)
                .containsEntry("new_visitors", 1L).containsEntry("existing_visitors", 1L)
                // c1: 14:01~14:05(240초) 이벤트 3개, c2: 14:03~14:06(180초) 이벤트 3개 → 이벤트 평균 210초
                .containsEntry("avg_session_seconds", 210);

        Map<String, Object> second = metrics("minutes_metrics", "date_time", ts(14, 10));
        // c2 는 14:03 에 이미 방문했으므로 기존 방문자, c3 는 신규. 14:20 클릭은 제외
        assertThat(second).containsEntry("clicks", 1L).containsEntry("visitors", 2L)
                .containsEntry("new_visitors", 1L).containsEntry("existing_visitors", 1L)
                .containsEntry("avg_session_seconds", 60);
    }

    @Test
    void rollupsSumLowerGranularity() {
        Map<String, Object> hourly = metrics("hourly_metrics", "date_time", ts(14, 0));
        assertThat(hourly).containsEntry("clicks", 5L).containsEntry("visitors", 5L)
                .containsEntry("new_visitors", 2L).containsEntry("existing_visitors", 3L)
                .containsEntry("avg_session_seconds", 90); // avg(210, 60, 0)

        assertThat(metrics("daily_metrics", "date", DAY)).containsEntry("clicks", 5L);
        assertThat(metrics("weekly_metrics", "date", DAY)).containsEntry("clicks", 5L);
    }

    @Test
    void clickSummaryPerSegment() {
        List<Map<String, Object>> minutes = jdbc.queryForList("""
                SELECT segment_value, total_clicks, total_users, avg_clicks_per_user
                FROM minutes_click_summary
                WHERE sdk_key = ? AND date_time = ? AND segment_type = 'user_gender'
                ORDER BY segment_value
                """, SDK, ts(14, 0));
        assertThat(minutes).containsExactly(
                Map.of("segment_value", "female", "total_clicks", 2L, "total_users", 1L, "avg_clicks_per_user", 2.0),
                Map.of("segment_value", "male", "total_clicks", 1L, "total_users", 1L, "avg_clicks_per_user", 1.0));

        // 일간 세그먼트 통계는 events 에서 다시 계산 (40대 c3 의 14:16, 14:20 클릭 포함)
        List<Map<String, Object>> daily = jdbc.queryForList("""
                SELECT segment_value, total_clicks, total_users
                FROM daily_click_summary
                WHERE sdk_key = ? AND date = ? AND segment_type = 'user_age'
                ORDER BY segment_value
                """, SDK, DAY);
        assertThat(daily).containsExactly(
                Map.of("segment_value", "20s", "total_clicks", 1L, "total_users", 1L),
                Map.of("segment_value", "30s", "total_clicks", 2L, "total_users", 1L),
                Map.of("segment_value", "40s", "total_clicks", 2L, "total_users", 1L));

        Long weeklyClicks = jdbc.queryForObject("""
                SELECT sum(total_clicks) FROM weekly_click_summary
                WHERE sdk_key = ? AND date = ? AND segment_type = 'device_type'
                """, Long.class, SDK, DAY);
        assertThat(weeklyClicks).isEqualTo(5L);
    }

    @Test
    void topElementsAreRankedPerSegmentValue() {
        List<Map<String, Object>> hourly = jdbc.queryForList("""
                SELECT rank, element, total_clicks
                FROM hourly_top_elements
                WHERE sdk_key = ? AND date_time = ? AND segment_type = 'device_type' AND segment_value = 'desktop'
                ORDER BY rank
                """, SDK, ts(14, 0));
        // desktop: Menu(c3 14:16, 14:20) 2회, Buy(c1) 1회
        assertThat(hourly).containsExactly(
                Map.of("rank", 1, "element", "Menu", "total_clicks", 2L),
                Map.of("rank", 2, "element", "Buy", "total_clicks", 1L));
    }

    @Test
    void userDistributionByAgeGroupAndDevice() {
        List<Map<String, Object>> daily = jdbc.queryForList("""
                SELECT dist_type, dist_value, user_count
                FROM daily_user_distribution
                WHERE sdk_key = ? AND date = ? AND segment_type = 'user_gender' AND segment_value = 'male'
                ORDER BY dist_type, dist_value
                """, SDK, DAY);
        assertThat(daily).containsExactly(
                Map.of("dist_type", "ageGroup", "dist_value", "20s", "user_count", 1L),
                Map.of("dist_type", "ageGroup", "dist_value", "40s", "user_count", 1L),
                Map.of("dist_type", "device", "dist_value", "desktop", "user_count", 2L));
    }

    @Test
    void pageStatsMergeNextPages() {
        Map<String, Object> minutes = jdbc.queryForMap("""
                SELECT page_views, page_exits, drop_rate, next_pages::text AS next_pages
                FROM minutes_page_stats
                WHERE sdk_key = ? AND date_time = ? AND page_path = '/'
                """, SDK, ts(14, 0));
        // s1: / → / → /cart, s2: / → / → (이탈)
        assertThat(minutes).containsEntry("page_views", 5L).containsEntry("page_exits", 1L)
                .containsEntry("drop_rate", 0.2)
                .containsEntry("next_pages", "[{\"to\": \"/\", \"count\": 3}, {\"to\": \"/cart\", \"count\": 1}]");

        Map<String, Object> hourly = jdbc.queryForMap("""
                SELECT page_views, page_exits, drop_rate, next_pages::text AS next_pages
                FROM hourly_page_stats
                WHERE sdk_key = ? AND date_time = ? AND page_path = '/'
                """, SDK, ts(14, 0));
        // 14:10 구간 s3: / → /, 이탈 / 14:20 구간 s3: / (이탈)
        assertThat(hourly).containsEntry("page_views", 8L).containsEntry("page_exits", 3L)
                .containsEntry("drop_rate", 0.375)
                .containsEntry("next_pages", "[{\"to\": \"/\", \"count\": 4}, {\"to\": \"/cart\", \"count\": 1}]");

        String weekly = jdbc.queryForObject("""
                SELECT next_pages::text FROM weekly_page_stats WHERE sdk_key = ? AND date = ? AND page_path = '/'
                """, String.class, SDK, DAY);
        assertThat(weekly).isEqualTo("[{\"to\": \"/\", \"count\": 4}, {\"to\": \"/cart\", \"count\": 1}]");
    }

    @Test
    void rerunReplacesBucketAndRecordsJobHistory() {
        int before = count("minutes_top_elements");
        launcher.run(Granularity.MINUTES, DAY.atTime(14, 7)); // 14:00 구간으로 정렬
        assertThat(count("minutes_top_elements")).isEqualTo(before);
        assertThat(metrics("minutes_metrics", "date_time", ts(14, 0))).containsEntry("clicks", 3L);

        Integer completed = jdbc.queryForObject("""
                SELECT count(*) FROM batch_job_execution e
                JOIN batch_job_instance i USING (job_instance_id)
                WHERE i.job_name = 'minutesAggregationJob' AND e.status = 'COMPLETED'
                """, Integer.class);
        assertThat(completed).isGreaterThanOrEqualTo(4);
        Integer steps = jdbc.queryForObject("""
                SELECT count(DISTINCT step_name) FROM batch_step_execution
                """, Integer.class);
        assertThat(steps).isEqualTo(4 * AggregationTarget.values().length);
    }

    @Test
    void backfillRebuildsWholeDay() {
        jdbc.update("DELETE FROM daily_metrics");
        jdbc.update("DELETE FROM hourly_page_stats");
        launcher.backfill(DAY, DAY);
        assertThat(metrics("daily_metrics", "date", DAY)).containsEntry("clicks", 5L).containsEntry("visitors", 5L);
        assertThat(jdbc.queryForObject("SELECT sum(page_views) FROM hourly_page_stats WHERE date_time = ?",
                Long.class, ts(14, 0))).isEqualTo(10L);
        assertThatThrownBy(() -> launcher.backfill(DAY, DAY.minusDays(1)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private Map<String, Object> metrics(String table, String column, Object bucket) {
        return jdbc.queryForMap("SELECT clicks, visitors, new_visitors, existing_visitors, avg_session_seconds FROM "
                + table + " WHERE sdk_key = ? AND " + column + " = ?", SDK, bucket);
    }

    private int count(String table) {
        return jdbc.queryForObject("SELECT count(*) FROM " + table, Integer.class);
    }

    private static Timestamp ts(int hour, int minute) {
        return Timestamp.from(DAY.atTime(hour, minute).atZone(KST).toInstant());
    }

    private void event(String name, LocalDateTime at, String clientId, String sessionId, String page,
                       String gender, int age, String device, String element) {
        jdbc.update("""
                INSERT INTO events (sdk_key, event_name, timestamp, client_id, session_id, page_path,
                    device_type, user_gender, user_age, element)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, SDK, name, Timestamp.from(at.atZone(KST).toInstant()), clientId, sessionId, page,
                device, gender, age, element);
    }
}
