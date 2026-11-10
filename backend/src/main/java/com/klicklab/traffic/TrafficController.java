package com.klicklab.traffic;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.AppClock;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import com.klicklab.common.Values;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.klicklab.common.Maps.obj;

@RestController
@RequestMapping("/api/traffic")
public class TrafficController {

    private final TrafficService trafficService;
    private final Db db;
    private final AppClock clock;

    public TrafficController(TrafficService trafficService, Db db, AppClock clock) {
        this.trafficService = trafficService;
        this.db = db;
        this.clock = clock;
    }

    /** Traffic 탭 통합 API (60초 캐시) */
    @GetMapping
    public Map<String, Object> dashboard(@AuthenticationPrincipal AuthUser user,
                                         @RequestParam(defaultValue = "daily") String period,
                                         @RequestParam(defaultValue = "all") String gender,
                                         @RequestParam(defaultValue = "all") String ageGroup) {
        return trafficService.dashboard(new TrafficService.Filters(user.sdkKey(), period, gender, ageGroup));
    }

    /** 일별 방문 트렌드 (최근 7일) */
    @GetMapping("/daily-visitors")
    public Map<String, Object> dailyVisitors(@AuthenticationPrincipal AuthUser user) {
        var filters = new TrafficService.Filters(user.sdkKey(), "daily", "all", "all");
        return Map.of("data", trafficService.visitorTrend(filters, clock.now()));
    }

    /** 채널(traffic_source)별 세션 전환율 */
    @GetMapping("/channel-conversion")
    public Map<String, Object> channelConversion(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        List<Map<String, Object>> rows = db.list("""
                WITH cc AS (
                    SELECT e.traffic_source, e.session_id, bool_or(ce.event_name IS NOT NULL) AS is_converted
                    FROM events e
                    LEFT JOIN conversion_events ce
                        ON ce.sdk_key = e.sdk_key AND ce.event_name = e.event_name AND ce.is_active = 1
                    WHERE e.sdk_key = :sdkKey AND e.timestamp >= :startTs AND e.timestamp < :endTs
                        AND e.traffic_source <> '' AND e.session_id <> ''
                    GROUP BY e.traffic_source, e.session_id
                )
                SELECT traffic_source AS channel,
                    count(*) AS total_sessions,
                    count(*) FILTER (WHERE is_converted) AS converted_sessions,
                    round(count(*) FILTER (WHERE is_converted) * 100.0 / count(*), 2) AS conversion_rate
                FROM cc
                GROUP BY traffic_source
                HAVING count(*) >= 5
                ORDER BY conversion_rate DESC, total_sessions DESC
                LIMIT 20
                """, Db.params("sdkKey", user.sdkKey(),
                "startTs", clock.startOf(range.start()), "endTs", clock.startOf(range.end().plusDays(1))));

        List<Map<String, Object>> data = rows.stream().map(r -> {
            String channel = Values.str(r.get("channel"));
            return obj("channel", channel.isEmpty() ? "unknown" : channel,
                    "source", channel.isEmpty() ? "unknown" : channel,
                    "medium", "", "campaign", "",
                    "totalSessions", Values.toLong(r.get("total_sessions")),
                    "convertedSessions", Values.toLong(r.get("converted_sessions")),
                    "conversionRate", Values.toDouble(r.get("conversion_rate")));
        }).toList();

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("period", range.start() + " ~ " + range.end());
        meta.put("totalChannels", data.size());
        meta.put("query_date", clock.now().toOffsetDateTime().toString());
        return Map.of("success", true, "data", data, "meta", meta);
    }
}
