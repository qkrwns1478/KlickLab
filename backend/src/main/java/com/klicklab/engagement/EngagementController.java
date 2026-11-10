package com.klicklab.engagement;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import com.klicklab.common.Sql;
import com.klicklab.common.Values;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

import static com.klicklab.common.Maps.obj;

@RestController
@RequestMapping("/api/engagement")
public class EngagementController {

    private final Db db;

    public EngagementController(Db db) {
        this.db = db;
    }

    /** 세션 참여도: 일별 평균 세션 시간 / 사용자당 세션 수 */
    @GetMapping("/overview")
    public Map<String, Object> overview(@AuthenticationPrincipal AuthUser user,
                                        @RequestParam(required = false) String startDate,
                                        @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date AS date,
                    sum(sessions) AS total_sessions,
                    sum(users) AS total_users,
                    round(sum(session_duration_sum) / NULLIF(sum(sessions), 0), 2) AS avg_session_seconds,
                    round(sum(sessions) / NULLIF(sum(users), 0), 2) AS sessions_per_user
                FROM agg_user_session_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY summary_date
                ORDER BY summary_date
                """, range.params(user.sdkKey()));

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("avgSessionSeconds", map(rows, r -> obj(
                "date", r.get("date"),
                "avgSessionSeconds", Values.toDouble(r.get("avg_session_seconds")))));
        data.put("sessionsPerUser", map(rows, r -> obj(
                "date", r.get("date"),
                "totalVisitors", Values.toLong(r.get("total_users")),
                "totalClicks", Values.toLong(r.get("total_sessions")), // 기존 API: 세션 수를 totalClicks 로 제공
                "sessionsPerUser", Values.toDouble(r.get("sessions_per_user")))));
        return Map.of("success", true, "data", data);
    }

    /** 페이지 평균 체류 시간 */
    @GetMapping("/page-times")
    public List<Map<String, Object>> pageTimes(@AuthenticationPrincipal AuthUser user,
                                               @RequestParam(required = false) String startDate,
                                               @RequestParam(required = false) String endDate,
                                               @RequestParam(defaultValue = "10") int limit) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT page_path,
                    round((sum(time_on_page_sum) / sum(page_views))::numeric, 1) AS average_time
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY page_path
                HAVING sum(page_views) > 0
                ORDER BY average_time DESC
                LIMIT :limit
                """, range.params(user.sdkKey()).addValue("limit", limit(limit)));
        return map(rows, r -> {
            double avg = Values.toDouble(r.get("average_time"));
            return obj("page", r.get("page_path"), "averageTime", avg, "averageTimeSeconds", avg * 60);
        });
    }

    @GetMapping("/bounce-rate")
    public List<Map<String, Object>> bounceRate(@AuthenticationPrincipal AuthUser user,
                                                @RequestParam(required = false) String startDate,
                                                @RequestParam(required = false) String endDate,
                                                @RequestParam(defaultValue = "10") int limit) {
        return exitRates(user, DateRange.required(startDate, endDate), limit);
    }

    @GetMapping("/exit-rate")
    public List<Map<String, Object>> exitRate(@AuthenticationPrincipal AuthUser user,
                                              @RequestParam(required = false) String startDate,
                                              @RequestParam(required = false) String endDate,
                                              @RequestParam(defaultValue = "5") int limit) {
        return exitRates(user, DateRange.required(startDate, endDate), limit);
    }

    @GetMapping("/page-views")
    public List<Map<String, Object>> pageViews(@AuthenticationPrincipal AuthUser user,
                                               @RequestParam(required = false) String startDate,
                                               @RequestParam(required = false) String endDate,
                                               @RequestParam(defaultValue = "10") int limit) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT page_path, sum(page_views) AS total_views
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY page_path
                HAVING sum(page_views) > 0
                ORDER BY total_views DESC
                LIMIT :limit
                """, range.params(user.sdkKey()).addValue("limit", limit(limit)));
        return map(rows, r -> obj("page", r.get("page_path"), "totalViews", Values.toLong(r.get("total_views"))));
    }

    @GetMapping("/view-counts")
    public List<Map<String, Object>> viewCounts(@AuthenticationPrincipal AuthUser user,
                                                @RequestParam(required = false) String startDate,
                                                @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date AS date, sum(page_views) AS total
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY summary_date
                ORDER BY summary_date
                """, range.params(user.sdkKey()));
        return map(rows, r -> obj("date", r.get("date"), "totalViews", Values.toLong(r.get("total"))));
    }

    @GetMapping("/click-counts")
    public List<Map<String, Object>> clickCounts(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date AS date, sum(event_count) AS total
                FROM agg_event_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    AND event_name IN %s
                GROUP BY summary_date
                ORDER BY summary_date
                """.formatted(Sql.CLICK_EVENTS), range.params(user.sdkKey()));
        return map(rows, r -> obj("date", r.get("date"), "totalClicks", Values.toLong(r.get("total"))));
    }

    /** 일/주(7일)/월(30일) 활성 사용자 */
    @GetMapping("/users-over-time")
    public List<Map<String, Object>> usersOverTime(@AuthenticationPrincipal AuthUser user,
                                                   @RequestParam(required = false) String startDate,
                                                   @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        return map(activeUsers(user, range), r -> obj(
                "date", r.get("date"),
                "dailyUsers", Values.toLong(r.get("dau")),
                "weeklyUsers", Values.toLong(r.get("wau")),
                "monthlyUsers", Values.toLong(r.get("mau"))));
    }

    @GetMapping("/event-counts")
    public List<Map<String, Object>> eventCounts(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date AS date, event_name, event_count, unique_users,
                    round(event_count::numeric / GREATEST(unique_users, 1), 2) AS avg_event_per_user
                FROM agg_event_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                ORDER BY summary_date, event_count DESC
                """, range.params(user.sdkKey()));
        return map(rows, r -> obj(
                "date", r.get("date"),
                "eventName", r.get("event_name"),
                "eventCount", Values.toLong(r.get("event_count")),
                "userCount", Values.toLong(r.get("unique_users")),
                "avgEventPerUser", Values.toDouble(r.get("avg_event_per_user"))));
    }

    @GetMapping("/page-stats")
    public List<Map<String, Object>> pageStats(@AuthenticationPrincipal AuthUser user,
                                               @RequestParam(required = false) String startDate,
                                               @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT p.summary_date AS date, p.page_path, p.page_views, p.unique_users,
                    round(p.page_views::numeric / NULLIF(p.unique_users, 0), 2) AS pageviews_per_user,
                    round((p.time_on_page_sum / NULLIF(p.unique_users, 0))::numeric, 2) AS avg_engagement_time_sec,
                    COALESCE(e.total_events, 0) AS total_events
                FROM agg_page_daily p
                LEFT JOIN (
                    SELECT summary_date, page_path, sum(event_count) AS total_events
                    FROM agg_event_page_daily
                    WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    GROUP BY summary_date, page_path
                ) e USING (summary_date, page_path)
                WHERE p.sdk_key = :sdkKey AND p.summary_date BETWEEN :start AND :end
                ORDER BY p.summary_date DESC, p.page_views DESC
                """, range.params(user.sdkKey()));
        return map(rows, r -> obj(
                "date", r.get("date"),
                "pagePath", r.get("page_path"),
                "pageViews", Values.toLong(r.get("page_views")),
                "activeUsers", Values.toLong(r.get("unique_users")),
                "pageviewsPerUser", Values.toDouble(r.get("pageviews_per_user")),
                "avgEngagementTimeSec", Values.toDouble(r.get("avg_engagement_time_sec")),
                "totalEvents", Values.toLong(r.get("total_events"))));
    }

    /** 시간 경과에 따른 방문 페이지 */
    @GetMapping("/visit-stats")
    public List<Map<String, Object>> visitStats(@AuthenticationPrincipal AuthUser user,
                                                @RequestParam(required = false) String startDate,
                                                @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date AS date, page_path, sessions, unique_users,
                    round((time_on_page_sum / NULLIF(unique_users, 0))::numeric, 2) AS avg_session_seconds
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                ORDER BY summary_date, sessions DESC
                """, range.params(user.sdkKey()));
        return map(rows, r -> obj(
                "date", r.get("date"),
                "pagePath", r.get("page_path"),
                "sessions", Values.toLong(r.get("sessions")),
                "activeUsers", Values.toLong(r.get("unique_users")),
                "newVisitors", Values.toLong(r.get("unique_users")),
                "avgSessionSeconds", Values.toDouble(r.get("avg_session_seconds"))));
    }

    /** 재방문 지표: DAU / WAU / MAU 및 비율 */
    @GetMapping("/revisit")
    public List<Map<String, Object>> revisit(@AuthenticationPrincipal AuthUser user,
                                             @RequestParam(required = false) String startDate,
                                             @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.required(startDate, endDate);
        return map(activeUsers(user, range), r -> {
            long dau = Values.toLong(r.get("dau"));
            long wau = Values.toLong(r.get("wau"));
            long mau = Values.toLong(r.get("mau"));
            return obj("date", r.get("date"), "dau", dau, "wau", wau, "mau", mau,
                    "dauWauRatio", ratio(dau, wau), "dauMauRatio", ratio(dau, mau), "wauMauRatio", ratio(wau, mau));
        });
    }

    private List<Map<String, Object>> activeUsers(AuthUser user, DateRange range) {
        return db.list("""
                SELECT d::date AS date,
                    (SELECT count(*) FROM agg_daily_users u
                      WHERE u.sdk_key = :sdkKey AND u.summary_date = d::date) AS dau,
                    (SELECT count(DISTINCT client_id) FROM agg_daily_users u
                      WHERE u.sdk_key = :sdkKey AND u.summary_date BETWEEN d::date - 6 AND d::date) AS wau,
                    (SELECT count(DISTINCT client_id) FROM agg_daily_users u
                      WHERE u.sdk_key = :sdkKey AND u.summary_date BETWEEN d::date - 29 AND d::date) AS mau
                FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
                ORDER BY 1
                """, range.params(user.sdkKey()));
    }

    private List<Map<String, Object>> exitRates(AuthUser user, DateRange range, int limit) {
        List<Map<String, Object>> rows = db.list("""
                SELECT page_path, sum(page_views) AS page_views, sum(exits) AS exits,
                    round(sum(exits) * 100.0 / sum(page_views), 2) AS exit_rate
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY page_path
                HAVING sum(page_views) > 0
                ORDER BY exit_rate DESC
                LIMIT :limit
                """, range.params(user.sdkKey()).addValue("limit", limit(limit)));
        return map(rows, r -> obj(
                "page_path", r.get("page_path"),
                "page_views", Values.toLong(r.get("page_views")),
                "exits", Values.toLong(r.get("exits")),
                "bounce_rate", Values.toDouble(r.get("exit_rate"))));
    }

    private static double ratio(long a, long b) {
        return b > 0 ? Values.round((double) a / b, 4) : 0;
    }

    private static int limit(int limit) {
        return Math.max(1, Math.min(limit, 1000));
    }

    private static List<Map<String, Object>> map(List<Map<String, Object>> rows,
                                                 Function<Map<String, Object>, Map<String, Object>> fn) {
        return rows.stream().map(fn).toList();
    }
}
