package com.klicklab.overview;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.AppClock;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import com.klicklab.common.Sql;
import com.klicklab.common.Values;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/overview")
public class OverviewController {

    private static final DateTimeFormatter MINUTE = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm");
    private static final int REALTIME_MINUTES = 30;

    private final Db db;
    private final AppClock clock;

    public OverviewController(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    /** 최근 30분 실시간 데이터 (events 원천 조회) */
    @GetMapping("/realtime")
    public Map<String, Object> realtime(@AuthenticationPrincipal AuthUser user) {
        ZonedDateTime now = clock.now();
        ZonedDateTime currentMinute = now.truncatedTo(ChronoUnit.MINUTES);
        var params = Db.params("sdkKey", user.sdkKey(),
                "since", now.minusMinutes(REALTIME_MINUTES).toOffsetDateTime(),
                "trendSince", currentMinute.minusMinutes(REALTIME_MINUTES - 1).toOffsetDateTime());

        long activeUsers = db.longValue("SELECT count(DISTINCT " + Sql.CLIENT + ") FROM events "
                + "WHERE sdk_key = :sdkKey AND timestamp >= :since", params);

        List<Map<String, Object>> locations = db.list("""
                SELECT city, count(*) AS page_views
                FROM events
                WHERE sdk_key = :sdkKey AND timestamp >= :since
                    AND event_name = 'page_view' AND city <> ''
                GROUP BY city
                ORDER BY page_views DESC
                LIMIT 10
                """, params);

        List<Map<String, Object>> trendRows = db.list("""
                SELECT to_char(date_trunc('minute', timestamp), 'YYYY-MM-DD"T"HH24:MI') AS minute,
                    count(DISTINCT %s) AS users
                FROM events
                WHERE sdk_key = :sdkKey AND timestamp >= :trendSince
                GROUP BY 1
                """.formatted(Sql.CLIENT), params);

        // 지역별 사용자 수: 페이지뷰 비율로 활성 사용자 수를 배분 (기존 로직 유지)
        long totalPageViews = locations.stream().mapToLong(r -> Values.toLong(r.get("page_views"))).sum();
        List<Map<String, Object>> topLocations = new ArrayList<>();
        long locationUsersSum = 0;
        for (Map<String, Object> row : locations) {
            double ratio = totalPageViews > 0 ? (double) Values.toLong(row.get("page_views")) / totalPageViews : 0;
            long estimated = Values.round(activeUsers * ratio);
            locationUsersSum += estimated;
            Map<String, Object> loc = new LinkedHashMap<>();
            loc.put("location", row.get("city"));
            loc.put("users", estimated);
            topLocations.add(loc);
        }
        if (locationUsersSum > activeUsers && activeUsers > 0) {
            double adjustment = (double) activeUsers / locationUsersSum;
            topLocations.forEach(loc -> loc.put("users", (long) Math.floor(Values.toLong(loc.get("users")) * adjustment)));
        }

        Map<String, Long> usersByMinute = new HashMap<>();
        trendRows.forEach(r -> usersByMinute.put(Values.str(r.get("minute")), Values.toLong(r.get("users"))));
        List<Map<String, Object>> trend = new ArrayList<>(REALTIME_MINUTES);
        for (int i = REALTIME_MINUTES - 1; i >= 0; i--) {
            String time = currentMinute.minusMinutes(i).format(MINUTE);
            trend.add(Map.of("time", time, "users", Math.min(usersByMinute.getOrDefault(time, 0L), activeUsers)));
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("activeUsers30min", activeUsers);
        data.put("trend", trend);
        data.put("topLocations", topLocations);
        return Map.of("data", data);
    }

    @GetMapping("/user-stats")
    public Map<String, Object> userStats(@AuthenticationPrincipal AuthUser user,
                                         @RequestParam(required = false) String startDate,
                                         @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date,
                    sum(users) AS active_users,
                    sum(sessions) AS sessions,
                    sum(session_duration_sum) AS session_duration_sum
                FROM agg_user_session_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY summary_date
                ORDER BY summary_date
                """, range.params(user.sdkKey()));

        long totalUsers = rows.stream().mapToLong(r -> Values.toLong(r.get("active_users"))).sum();
        long totalSessions = rows.stream().mapToLong(r -> Values.toLong(r.get("sessions"))).sum();
        long totalDuration = rows.stream().mapToLong(r -> Values.toLong(r.get("session_duration_sum"))).sum();
        long avgSessionDuration = totalSessions > 0 ? Values.round((double) totalDuration / totalSessions) : 0;
        long conversionRate = totalSessions > 0 && totalUsers > 0
                ? Values.round((double) totalSessions / totalUsers * 100) : 0;

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("activeUsers", totalUsers);
        data.put("sessions", totalSessions);
        data.put("avgSessionDuration", avgSessionDuration);
        data.put("conversionRate", conversionRate);
        data.put("engagedSessions", totalSessions);

        // 기존 API 와 동일한 임시 값 (증감률 계산은 미구현)
        Map<String, Object> changes = new LinkedHashMap<>();
        changes.put("activeUsers", 5.2);
        changes.put("sessions", 3.8);
        changes.put("avgSessionDuration", -2.1);
        changes.put("conversionRate", 1.5);
        changes.put("engagedSessions", 3.8);

        List<Map<String, Object>> trend = rows.stream().map(r -> {
            Map<String, Object> t = new LinkedHashMap<>();
            t.put("date", r.get("summary_date"));
            t.put("users", Values.toLong(r.get("active_users")));
            t.put("sessions", Values.toLong(r.get("sessions")));
            return t;
        }).toList();

        return Map.of("data", data, "changes", changes, "trend", trend);
    }

    @GetMapping("/traffic-stats")
    public Map<String, Object> trafficStats(@AuthenticationPrincipal AuthUser user,
                                            @RequestParam(required = false) String startDate,
                                            @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        List<Map<String, Object>> rows = db.list("""
                SELECT COALESCE(NULLIF(traffic_source, ''), 'direct') AS source, sum(users) AS users
                FROM agg_traffic_hourly
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY 1
                ORDER BY users DESC
                LIMIT 10
                """, range.params(user.sdkKey()));
        List<Map<String, Object>> sources = rows.stream()
                .map(r -> Map.<String, Object>of("source", r.get("source"), "users", Values.toLong(r.get("users"))))
                .toList();
        return Map.of("data", Map.of("trafficSources", sources));
    }

    @GetMapping("/page-stats")
    public Map<String, Object> pageStats(@AuthenticationPrincipal AuthUser user,
                                         @RequestParam(required = false) String startDate,
                                         @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        List<Map<String, Object>> rows = db.list("""
                SELECT page_path AS page, sum(page_views) AS views
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY page_path
                ORDER BY views DESC
                LIMIT 10
                """, range.params(user.sdkKey()));
        List<Map<String, Object>> pages = rows.stream()
                .map(r -> Map.<String, Object>of("page", r.get("page"), "views", Values.toLong(r.get("views"))))
                .toList();
        return Map.of("data", Map.of("topPages", pages));
    }

    @GetMapping("/event-stats")
    public Map<String, Object> eventStats(@AuthenticationPrincipal AuthUser user,
                                          @RequestParam(required = false) String startDate,
                                          @RequestParam(required = false) String endDate,
                                          @RequestParam(defaultValue = "10") int limit) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        List<Map<String, Object>> rows = db.list("""
                SELECT event_name AS event, sum(event_count) AS count
                FROM agg_event_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY event_name
                ORDER BY count DESC
                LIMIT :limit
                """, range.params(user.sdkKey()).addValue("limit", Math.max(1, limit)));
        List<Map<String, Object>> events = rows.stream()
                .map(r -> Map.<String, Object>of("event", r.get("event"), "count", Values.toLong(r.get("count"))))
                .toList();
        return Map.of("data", Map.of("topEvents", events));
    }
}
