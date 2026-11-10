package com.klicklab.acquisition;

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

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.klicklab.common.Maps.obj;

/** 유입 분석 */
@RestController
@RequestMapping("/api/acquisition")
public class AcquisitionController {

    private static final String DIRECT = "traffic_source IN ('', 'direct', '(direct)')";
    /** tablet 은 mobile 로, 그 외 미분류는 desktop 으로 분류 (기존 로직) */
    private static final String DEVICE_GROUP =
            "CASE WHEN lower(device_type) IN ('mobile', 'tablet') THEN 'mobile' ELSE 'desktop' END";

    private final Db db;
    private final AppClock clock;

    public AcquisitionController(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    @GetMapping("/overview")
    public Map<String, Object> overview(@AuthenticationPrincipal AuthUser user,
                                        @RequestParam(required = false) String startDate,
                                        @RequestParam(required = false) String endDate) {
        Map<String, Object> row = db.one("""
                SELECT COALESCE(sum(funnel_visits) FILTER (WHERE NOT %1$s), 0) AS visits,
                       COALESCE(sum(funnel_engaged) FILTER (WHERE NOT %1$s), 0) AS engaged,
                       COALESCE(sum(funnel_converted) FILTER (WHERE NOT %1$s), 0) AS converted,
                       COALESCE(sum(funnel_visits) FILTER (WHERE %1$s), 0) AS direct_visits
                  FROM agg_traffic_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                """.formatted(DIRECT), range(startDate, endDate).params(user.sdkKey()));

        // 마케팅 관점: Direct 를 제외한 채널만 유입으로 계산 (기존 로직)
        long visits = Values.toLong(row.get("visits"));
        long engaged = Values.toLong(row.get("engaged"));
        long converted = Values.toLong(row.get("converted"));
        long directVisits = Values.toLong(row.get("direct_visits"));
        long engagementRate = visits > 0 ? Values.round((double) engaged / visits * 100) : 0;
        long directTrafficRate = visits > 0 ? Values.round((double) directVisits / visits * 100) : 0;

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("active_users", visits);
        body.put("converted_users", converted);
        body.put("engaged_users", engaged);
        body.put("engagement_rate", engagementRate);
        body.put("direct_traffic_rate", directTrafficRate);
        body.put("total_visits", visits);
        body.put("direct_visits", directVisits);
        // 기존 필드 유지 (호환성)
        body.put("totalUsers", visits);
        body.put("totalSessions", visits);
        body.put("avgSessionDuration", engagementRate);
        body.put("bounceRate", directTrafficRate);
        return body;
    }

    @GetMapping("/hourly-trend")
    public List<Map<String, Object>> hourlyTrend(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        Map<Integer, Long> byHour = new HashMap<>();
        db.list("""
                SELECT summary_hour, sum(users) AS users
                  FROM agg_user_session_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                 GROUP BY summary_hour
                """, range(startDate, endDate).params(user.sdkKey()))
                .forEach(r -> byHour.put((int) Values.toLong(r.get("summary_hour")), Values.toLong(r.get("users"))));

        List<Map<String, Object>> trend = new ArrayList<>(24);
        for (int h = 0; h < 24; h++) {
            long users = byHour.getOrDefault(h, 0L);
            // 신규/기존 구분 데이터가 없어 기존 API 와 동일하게 전체를 신규로 표시
            trend.add(obj("hour", String.format("%02d", h), "total_users", users,
                    "new_users", users, "existing_users", 0));
        }
        return trend;
    }

    @GetMapping("/top-channels")
    public List<Map<String, Object>> topChannels(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        return db.list("""
                SELECT COALESCE(NULLIF(traffic_source, ''), 'direct') AS channel, sum(users) AS users
                  FROM agg_traffic_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                 GROUP BY 1
                 ORDER BY users DESC
                 LIMIT 10
                """, range(startDate, endDate).params(user.sdkKey())).stream()
                .map(r -> obj("channel", r.get("channel"), "users", Values.toLong(r.get("users")), "clicks", 0))
                .toList();
    }

    @GetMapping("/platform-analysis")
    public Map<String, Object> platformAnalysis(@AuthenticationPrincipal AuthUser user,
                                                @RequestParam(required = false) String startDate,
                                                @RequestParam(required = false) String endDate) {
        var params = range(startDate, endDate).params(user.sdkKey());
        List<Map<String, Object>> device = db.list("""
                SELECT %s AS type, sum(users) AS users
                  FROM agg_user_session_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end AND users > 0
                 GROUP BY 1
                 ORDER BY users DESC
                 LIMIT 5
                """.formatted(DEVICE_GROUP), params);
        List<Map<String, Object>> browser = db.list("""
                SELECT COALESCE(NULLIF(browser, ''), 'Unknown') AS name, sum(users) AS users
                  FROM agg_user_session_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end AND users > 0
                 GROUP BY 1
                 ORDER BY users DESC
                 LIMIT 5
                """, params);
        return Map.of("device", device, "browser", browser);
    }

    @GetMapping("/funnel-conversion")
    public List<Map<String, Object>> funnelConversion(@AuthenticationPrincipal AuthUser user,
                                                      @RequestParam(required = false) String startDate,
                                                      @RequestParam(required = false) String endDate) {
        Map<String, Object> row = db.one("""
                SELECT COALESCE(sum(funnel_visits), 0) AS visits,
                       COALESCE(sum(funnel_engaged), 0) AS engaged,
                       COALESCE(sum(funnel_converted), 0) AS converted
                  FROM agg_traffic_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                """, range(startDate, endDate).params(user.sdkKey()));
        return List.of(
                obj("step", "방문", "users", Values.toLong(row.get("visits"))),
                obj("step", "참여", "users", Values.toLong(row.get("engaged"))),
                obj("step", "전환", "users", Values.toLong(row.get("converted"))));
    }

    /** 채널 x 디바이스 사용자/세션 수 */
    @GetMapping("/channel-groups")
    public List<Map<String, Object>> channelGroups(@AuthenticationPrincipal AuthUser user,
                                                   @RequestParam(required = false) String startDate,
                                                   @RequestParam(required = false) String endDate) {
        DateRange range = range(startDate, endDate);
        return db.list("""
                SELECT COALESCE(NULLIF(traffic_source, ''), 'direct') AS channel,
                       %s AS device,
                       count(DISTINCT %s) AS users,
                       count(DISTINCT session_id) AS sessions
                  FROM events
                 WHERE sdk_key = :sdkKey AND timestamp >= :startTs AND timestamp < :endTs
                 GROUP BY 1, 2
                 ORDER BY users DESC
                """.formatted(DEVICE_GROUP, Sql.CLIENT), Db.params("sdkKey", user.sdkKey(),
                "startTs", clock.startOf(range.start()), "endTs", clock.startOf(range.end().plusDays(1))));
    }

    @GetMapping("/campaigns")
    public List<Map<String, Object>> campaigns(@AuthenticationPrincipal AuthUser user,
                                               @RequestParam(required = false) String startDate,
                                               @RequestParam(required = false) String endDate) {
        return db.list("""
                SELECT COALESCE(NULLIF(traffic_campaign, ''), 'none') AS campaign,
                       sum(users) AS users, sum(sessions) AS sessions
                  FROM agg_traffic_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                 GROUP BY 1
                 ORDER BY users DESC
                 LIMIT 10
                """, range(startDate, endDate).params(user.sdkKey()));
    }

    /** 도시별 사용자 (기존 API 명 유지: top-countries) */
    @GetMapping("/top-countries")
    public List<Map<String, Object>> topCountries(@AuthenticationPrincipal AuthUser user,
                                                  @RequestParam(required = false) String startDate,
                                                  @RequestParam(required = false) String endDate) {
        return db.list("""
                SELECT COALESCE(NULLIF(city, ''), 'unknown') AS city, sum(users) AS users
                  FROM agg_user_session_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                 GROUP BY 1
                 ORDER BY users DESC
                 LIMIT 10
                """, range(startDate, endDate).params(user.sdkKey()));
    }

    /** Sankey 클릭 플로우 (미구현: 기존과 동일하게 빈 배열) */
    @GetMapping("/click-flow")
    public List<Object> clickFlow() {
        return List.of();
    }

    @GetMapping("/landing-pages")
    public List<Map<String, Object>> landingPages(@AuthenticationPrincipal AuthUser user,
                                                  @RequestParam(required = false) String startDate,
                                                  @RequestParam(required = false) String endDate) {
        return db.list("""
                SELECT COALESCE(NULLIF(landing_page, ''), '/') AS page,
                       sum(sessions) AS sessions,
                       sum(users) AS users,
                       sum(funnel_visits) AS visits,
                       sum(funnel_engaged) AS engaged,
                       sum(funnel_converted) AS converted,
                       sum(bounced_sessions) AS bounced
                  FROM agg_traffic_hourly
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                 GROUP BY 1
                 ORDER BY sessions DESC
                 LIMIT 10
                """, range(startDate, endDate).params(user.sdkKey())).stream().map(r -> {
            long sessions = Values.toLong(r.get("sessions"));
            long visits = Values.toLong(r.get("visits"));
            Map<String, Object> page = new LinkedHashMap<>(r);
            page.put("engagement_rate", visits > 0 ? Values.round(Values.toDouble(r.get("engaged")) / visits * 100) : 0);
            page.put("conversion_rate", visits > 0 ? Values.round(Values.toDouble(r.get("converted")) / visits * 100) : 0);
            page.put("bounce_rate", sessions > 0 ? Values.round(Values.toDouble(r.get("bounced")) / sessions * 100) : 0);
            return page;
        }).toList();
    }

    private DateRange range(String startDate, String endDate) {
        return DateRange.orDefault(startDate, endDate, clock, 7);
    }
}
