package com.klicklab.stats;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.AppClock;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import com.klicklab.common.Sql;
import com.klicklab.common.Values;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/stats")
public class StatsController {

    /** 전환 이벤트 → (시작 페이지, 완료 페이지) 매핑 */
    static final Map<String, String[]> CONVERSION_PAGES = Map.of(
            "is_payment", new String[]{"/cart", "/checkout/success"},
            "is_signup", new String[]{"/signup", "/signup/success"},
            "add_to_cart", new String[]{"/products", "/cart"},
            "contact_submit", new String[]{"/contact", "/contact/success"});

    private final Db db;
    private final AppClock clock;

    public StatsController(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    /** 방문자: 오늘(실시간) / 어제 / 최근 6일 추이 */
    @GetMapping("/visitors")
    public Map<String, Object> visitors(@AuthenticationPrincipal AuthUser user) {
        LocalDate today = clock.today();
        var params = Db.params("sdkKey", user.sdkKey(), "today", today, "yesterday", today.minusDays(1),
                "weekAgo", today.minusDays(6), "todayStart", clock.startOf(today));

        List<Map<String, Object>> trend = db.list("""
                SELECT summary_date AS date, sum(users) AS visitors
                FROM agg_user_session_daily
                WHERE sdk_key = :sdkKey AND summary_date >= :weekAgo AND summary_date < :today
                GROUP BY summary_date
                ORDER BY summary_date
                """, params).stream().map(r -> Map.<String, Object>of(
                "date", r.get("date"), "visitors", Values.toLong(r.get("visitors")))).toList();

        long yesterday = db.longValue("""
                SELECT COALESCE(sum(users), 0) FROM agg_user_session_daily
                WHERE sdk_key = :sdkKey AND summary_date = :yesterday
                """, params);
        long todayVisitors = db.longValue("SELECT count(DISTINCT " + Sql.CLIENT + ") FROM events "
                + "WHERE sdk_key = :sdkKey AND timestamp >= :todayStart", params);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("today", todayVisitors);
        body.put("yesterday", yesterday);
        body.put("trend", trend);
        return body;
    }

    /** 클릭 수: 오늘(실시간) / 어제 */
    @GetMapping("/clicks")
    public Map<String, Object> clicks(@AuthenticationPrincipal AuthUser user) {
        LocalDate today = clock.today();
        var params = Db.params("sdkKey", user.sdkKey(), "yesterday", today.minusDays(1),
                "todayStart", clock.startOf(today));
        long yesterday = db.longValue("""
                SELECT COALESCE(sum(event_count), 0) FROM agg_event_daily
                WHERE sdk_key = :sdkKey AND summary_date = :yesterday AND event_name = 'auto_click'
                """, params);
        long todayClicks = db.longValue("""
                SELECT count(*) FROM events
                WHERE sdk_key = :sdkKey AND event_name = 'auto_click' AND timestamp >= :todayStart
                """, params);
        return Map.of("today", todayClicks, "yesterday", yesterday);
    }

    /** 오늘 가장 많이 클릭된 요소 Top 5 */
    @GetMapping("/top-clicks")
    public Map<String, Object> topClicks(@AuthenticationPrincipal AuthUser user) {
        List<Map<String, Object>> items = db.list("""
                SELECT element AS label, count(*) AS count
                FROM events
                WHERE sdk_key = :sdkKey AND event_name = 'auto_click'
                    AND timestamp >= :todayStart AND element <> ''
                GROUP BY element
                ORDER BY count DESC
                LIMIT 5
                """, Db.params("sdkKey", user.sdkKey(), "todayStart", clock.startOf(clock.today())));
        return Map.of("items", items);
    }

    /** baseTime 기준 period 분 동안의 클릭 수를 step 분 단위로 집계 */
    @GetMapping("/click-trend")
    public Map<String, Object> clickTrend(@AuthenticationPrincipal AuthUser user,
                                          @RequestParam(required = false) String baseTime,
                                          @RequestParam(defaultValue = "60") String period,
                                          @RequestParam(defaultValue = "5") String step) {
        int periodMinutes = positiveInt(period, 60);
        int stepMinutes = positiveInt(step, 5);
        List<Map<String, Object>> rows = db.list("""
                WITH b AS (
                    SELECT CAST(:base AS timestamptz) AS base,
                        date_trunc('minute', CAST(:base AS timestamptz)) AS base_min
                )
                SELECT to_char(b.base_min + make_interval(mins =>
                           (((extract(epoch FROM date_trunc('minute', e.timestamp) - b.base_min) / 60)::int
                             / :step) * :step)), 'HH24:MI') AS time,
                    count(*) AS count
                FROM events e CROSS JOIN b
                WHERE e.sdk_key = :sdkKey AND e.event_name = 'auto_click'
                    AND e.timestamp >= b.base - make_interval(mins => :period)
                GROUP BY 1
                ORDER BY 1
                """, Db.params("sdkKey", user.sdkKey(), "base", parseBaseTime(baseTime),
                "step", stepMinutes, "period", periodMinutes));
        return Map.of("data", rows);
    }

    /** 오늘 페이지별 이탈률 Top 5 */
    @GetMapping("/dropoff-summary")
    public Map<String, Object> dropoffSummary(@AuthenticationPrincipal AuthUser user) {
        List<Map<String, Object>> rows = db.list("""
                SELECT page_path AS page,
                    round(exits * 100.0 / page_views, 1) AS "dropRate"
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date = :today AND page_views > 0
                ORDER BY "dropRate" DESC
                LIMIT 5
                """, Db.params("sdkKey", user.sdkKey(), "today", clock.today()));
        return Map.of("data", rows);
    }

    /** 최근 1일 페이지 전이(Sankey). segment: converted | abandoned_cart */
    @GetMapping("/userpath-summary")
    public Map<String, Object> userpathSummary(@AuthenticationPrincipal AuthUser user,
                                               @RequestParam(required = false) String segment,
                                               @RequestParam(defaultValue = "90") String threshold) {
        String sessionFilter = switch (segment == null ? "" : segment) {
            case "converted" -> """
                    AND session_id IN (
                        SELECT session_id FROM events
                        WHERE sdk_key = :sdkKey AND event_name = 'page_view' AND timestamp >= :since
                        GROUP BY session_id
                        HAVING min(timestamp) FILTER (WHERE page_path = :fromPage) <
                               min(timestamp) FILTER (WHERE page_path = :toPage))
                    """;
            case "abandoned_cart" -> """
                    AND session_id IN (
                        SELECT session_id FROM events
                        WHERE sdk_key = :sdkKey AND event_name = 'page_view' AND timestamp >= :since
                        GROUP BY session_id
                        HAVING min(timestamp) FILTER (WHERE page_path = :fromPage) IS NOT NULL
                            AND min(timestamp) FILTER (WHERE page_path = :toPage) IS NULL)
                    """;
            default -> "";
        };
        double ratio = positiveInt(threshold, 90) / 100.0;

        List<Map<String, Object>> rows = db.list("""
                WITH pv AS (
                    SELECT session_id, page_path, timestamp, id
                    FROM events
                    WHERE sdk_key = :sdkKey AND event_name = 'page_view' AND page_path <> ''
                        AND session_id <> '' AND timestamp >= :since
                        %s
                ), pairs AS (
                    SELECT page_path AS src,
                        lead(page_path) OVER (PARTITION BY session_id ORDER BY timestamp, id) AS dst
                    FROM pv
                ), ranked AS (
                    SELECT src, dst, count(*) AS value
                    FROM pairs WHERE dst IS NOT NULL
                    GROUP BY src, dst
                ), cumulated AS (
                    SELECT src, dst, value,
                        sum(value) OVER (ORDER BY value DESC, src, dst
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running,
                        sum(value) OVER () AS total
                    FROM ranked
                )
                SELECT src AS "from", dst AS "to", value
                FROM cumulated
                WHERE running <= total * :ratio
                ORDER BY value DESC
                LIMIT 500
                """.formatted(sessionFilter), Db.params("sdkKey", user.sdkKey(),
                "since", clock.now().minusDays(1).toOffsetDateTime(),
                "fromPage", "/cart", "toPage", "/checkout/success", "ratio", ratio));
        return Map.of("data", rows);
    }

    /** 전환 경로 Top N */
    @GetMapping("/userpath-summary/conversion-top3")
    public Map<String, Object> conversionTop3(@AuthenticationPrincipal AuthUser user,
                                              @RequestParam(required = false) String fromPage,
                                              @RequestParam(required = false) String toPage,
                                              @RequestParam(required = false) String event,
                                              @RequestParam(defaultValue = "3") String limit,
                                              @RequestParam(required = false) String startDate,
                                              @RequestParam(required = false) String endDate) {
        if (event != null && !event.isBlank()) {
            String[] pages = CONVERSION_PAGES.get(event);
            fromPage = pages == null ? null : pages[0];
            toPage = pages == null ? null : pages[1];
        }
        if (isBlank(fromPage) || isBlank(toPage)) {
            String[] pages = currentConversionPages(user.sdkKey());
            fromPage = isBlank(fromPage) ? pages[0] : fromPage;
            toPage = isBlank(toPage) ? pages[1] : toPage;
        }
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        MapSqlParameterSource params = Db.params("sdkKey", user.sdkKey(), "fromPage", fromPage, "toPage", toPage,
                "start", clock.startOf(range.start()), "end", clock.startOf(range.end().plusDays(1)),
                "limit", positiveInt(limit, 3));

        String sessionsCte = """
                a AS (
                    SELECT session_id, min(timestamp) AS a_time
                    FROM events
                    WHERE sdk_key = :sdkKey AND page_path = :fromPage
                        AND timestamp >= :start AND timestamp < :end AND session_id <> ''
                    GROUP BY session_id
                ),
                b AS (
                    SELECT session_id, min(timestamp) AS b_time
                    FROM events
                    WHERE sdk_key = :sdkKey AND page_path = :toPage
                        AND timestamp >= :start AND timestamp < :end AND session_id <> ''
                    GROUP BY session_id
                ),
                ab AS (
                    SELECT a.session_id
                    FROM a JOIN b USING (session_id)
                    WHERE b.b_time > a.a_time
                )
                """;

        long totalFromPage = db.longValue("""
                SELECT count(DISTINCT session_id) FROM events
                WHERE sdk_key = :sdkKey AND page_path = :fromPage AND timestamp >= :start AND timestamp < :end
                """, params);
        long totalConversion = db.longValue("WITH " + sessionsCte + " SELECT count(*) FROM ab", params);

        List<Map<String, Object>> pathRows = db.list("WITH " + sessionsCte + """
                , fp AS (
                    SELECT session_id, array_agg(page_path ORDER BY timestamp, id) AS path
                    FROM events
                    WHERE sdk_key = :sdkKey AND event_name = 'page_view' AND page_path <> ''
                        AND timestamp >= :start AND timestamp < :end
                        AND session_id IN (SELECT session_id FROM a)
                    GROUP BY session_id
                ), lp AS (
                    SELECT array_to_string(
                               CASE WHEN array_position(fp.path, CAST(:toPage AS text)) IS NOT NULL
                                    THEN fp.path[1 : array_position(fp.path, CAST(:toPage AS text))]
                                    ELSE fp.path END, ' → ') AS path_string,
                        (ab.session_id IS NOT NULL) AS is_converted
                    FROM fp LEFT JOIN ab USING (session_id)
                )
                SELECT path_string,
                    count(*) AS total_sessions,
                    count(*) FILTER (WHERE is_converted) AS conversion_count
                FROM lp
                GROUP BY path_string
                HAVING count(*) FILTER (WHERE is_converted) > 0
                ORDER BY conversion_count DESC
                LIMIT :limit
                """, params);

        List<Map<String, Object>> data = new ArrayList<>();
        for (int i = 0; i < pathRows.size(); i++) {
            Map<String, Object> row = pathRows.get(i);
            long conversions = Values.toLong(row.get("conversion_count"));
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("path", Arrays.asList(Values.str(row.get("path_string")).split(" → ")));
            item.put("conversionCount", conversions);
            item.put("conversionRate", totalFromPage > 0 ? Values.round((double) conversions / totalFromPage * 1000) / 10.0 : 0);
            item.put("share", totalConversion > 0 ? Values.round((double) conversions / totalConversion * 1000) / 10.0 : 0);
            item.put("rank", i + 1);
            data.add(item);
        }
        double avgRate = data.stream().mapToDouble(d -> Values.toDouble(d.get("conversionRate"))).average().orElse(0);
        for (Map<String, Object> item : data) {
            item.put("compareToAvg", avgRate > 0
                    ? Values.round(Values.toDouble(item.get("conversionRate")) / avgRate * 10) / 10.0
                    : "-");
        }
        return Map.of("data", data, "totalConversion", totalConversion);
    }

    /** 세션별 경로 (type=url → url_path, 그 외 → event_path). 기본: 어제 */
    @GetMapping("/sankey-paths")
    public Map<String, Object> sankeyPaths(@AuthenticationPrincipal AuthUser user,
                                           @RequestParam(required = false) String type,
                                           @RequestParam(required = false) String startDate,
                                           @RequestParam(required = false) String endDate) {
        String column = "url".equals(type) ? "url_path" : "event_path";
        LocalDate yesterday = clock.today().minusDays(1);
        DateRange range = isBlank(startDate) || isBlank(endDate)
                ? new DateRange(yesterday, yesterday)
                : DateRange.required(startDate, endDate);
        List<Map<String, Object>> rows = db.list(
                "SELECT " + column + " FROM agg_sankey_paths_daily "
                        + "WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end",
                range.params(user.sdkKey()));
        return Map.of("data", rows);
    }

    private String[] currentConversionPages(String sdkKey) {
        Object event = db.one("SELECT event FROM users WHERE sdk_key = :sdkKey", Db.params("sdkKey", sdkKey))
                .get("event");
        return CONVERSION_PAGES.getOrDefault(Values.str(event), CONVERSION_PAGES.get("is_payment"));
    }

    private OffsetDateTime parseBaseTime(String value) {
        if (!isBlank(value)) {
            String v = value.trim();
            try {
                return OffsetDateTime.parse(v);
            } catch (DateTimeParseException ignored) {
                // fall through
            }
            try {
                return Instant.parse(v).atZone(clock.zone()).toOffsetDateTime();
            } catch (DateTimeParseException ignored) {
                // fall through
            }
            try {
                return LocalDateTime.parse(v.replace(' ', 'T')).atZone(clock.zone()).toOffsetDateTime();
            } catch (DateTimeParseException ignored) {
                // fall through
            }
        }
        return clock.now().toOffsetDateTime();
    }

    private static int positiveInt(String value, int fallback) {
        try {
            int parsed = Integer.parseInt(value.trim());
            return parsed > 0 ? parsed : fallback;
        } catch (NumberFormatException | NullPointerException e) {
            return fallback;
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
