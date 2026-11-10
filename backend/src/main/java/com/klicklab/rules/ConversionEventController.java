package com.klicklab.rules;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.AppClock;
import com.klicklab.common.Db;
import com.klicklab.common.DateRange;
import com.klicklab.common.Values;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 전환 이벤트 관리 (ClickHouse conversion_events + dictionary → PostgreSQL 테이블) */
@RestController
@RequestMapping("/api/conversion-events")
public class ConversionEventController {

    public record ConversionEventRequest(String event_name, String description) {
    }

    private final Db db;
    private final AppClock clock;

    public ConversionEventController(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    @GetMapping
    public List<Map<String, Object>> list(@AuthenticationPrincipal AuthUser user) {
        return db.list("""
                SELECT event_name, description, is_active, created_at, updated_at
                FROM conversion_events
                WHERE sdk_key = :sdkKey AND is_active = 1
                ORDER BY created_at DESC
                """, Db.params("sdkKey", user.sdkKey()));
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(@AuthenticationPrincipal AuthUser user,
                                                      @RequestBody ConversionEventRequest body) {
        if (body.event_name() == null || body.event_name().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "Event name is required"));
        }
        db.update("""
                INSERT INTO conversion_events (sdk_key, event_name, description, is_active)
                VALUES (:sdkKey, :eventName, :description, 1)
                ON CONFLICT (sdk_key, event_name) DO UPDATE
                    SET description = EXCLUDED.description, is_active = 1, updated_at = now()
                """, Db.params("sdkKey", user.sdkKey(), "eventName", body.event_name(),
                "description", body.description() == null ? "" : body.description()));
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(Map.of("message", "Conversion event created successfully", "event_name", body.event_name()));
    }

    /** 소프트 삭제 (is_active = 0) */
    @DeleteMapping("/{eventName}")
    public Map<String, Object> delete(@AuthenticationPrincipal AuthUser user, @PathVariable String eventName) {
        db.update("""
                UPDATE conversion_events SET is_active = 0, updated_at = now()
                WHERE sdk_key = :sdkKey AND event_name = :eventName
                """, Db.params("sdkKey", user.sdkKey(), "eventName", eventName));
        return Map.of("message", "Conversion event deleted successfully");
    }

    /** 일자별 전환 통계 (start_date/end_date: yyyy-MM-dd, 기본 최근 8일) */
    @GetMapping("/stats")
    public Map<String, Object> stats(@AuthenticationPrincipal AuthUser user,
                                     @RequestParam(name = "start_date", required = false) String startDate,
                                     @RequestParam(name = "end_date", required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 8);
        var params = Db.params("sdkKey", user.sdkKey(), "start", range.start(), "end", range.end());

        List<Map<String, Object>> overall = db.list("""
                SELECT summary_date,
                    sum(conversions) AS conversions,
                    sum(sessions) AS sessions,
                    round(sum(conversions) * 100.0 / NULLIF(sum(sessions), 0), 2) AS conversion_rate
                FROM agg_traffic_hourly
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY summary_date
                ORDER BY summary_date DESC
                """, params);

        List<Map<String, Object>> byEvent = db.list("""
                SELECT d.event_name,
                    sum(d.event_count) AS total_count,
                    sum(d.unique_users) AS unique_users,
                    d.summary_date
                FROM agg_event_daily d
                JOIN conversion_events ce
                    ON ce.sdk_key = d.sdk_key AND ce.event_name = d.event_name AND ce.is_active = 1
                WHERE d.sdk_key = :sdkKey AND d.summary_date BETWEEN :start AND :end
                GROUP BY d.event_name, d.summary_date
                ORDER BY d.summary_date DESC, total_count DESC
                """, params);

        return Map.of("overall", overall, "byEvent", byEvent);
    }

    /** 전환 이벤트로 등록 가능한 사용자 정의 이벤트 (event_rules / event_button 에서 정의된 것) */
    @GetMapping("/available")
    public Map<String, Object> available(@AuthenticationPrincipal AuthUser user) {
        var params = Db.params("sdkKey", user.sdkKey());

        List<String> registered = db.list(
                        "SELECT event_name FROM conversion_events WHERE sdk_key = :sdkKey AND is_active = 1", params)
                .stream().map(r -> Values.str(r.get("event_name"))).toList();

        List<Map<String, Object>> ruleEvents = db.list("""
                SELECT r.new_event_name AS event_name,
                    'rule' AS source_type,
                    count(*) AS definition_count,
                    to_char(max(r.created_at), 'YYYY-MM-DD') AS created_date
                FROM event_rules r
                WHERE r.sdk_key = :sdkKey
                    AND NOT EXISTS (
                        SELECT 1 FROM conversion_events ce
                        WHERE ce.sdk_key = r.sdk_key AND ce.event_name = r.new_event_name
                            AND ce.is_active = 1
                    )
                GROUP BY r.new_event_name
                """, params);

        List<Map<String, Object>> buttonEvents = db.list("""
                SELECT b.event_name,
                    'button' AS source_type,
                    count(*) AS definition_count,
                    to_char(max(b.created_at), 'YYYY-MM-DD') AS created_date,
                    array_agg(b.description ORDER BY b.created_at) AS descriptions
                FROM event_button b
                WHERE b.sdk_key = :sdkKey
                    AND NOT EXISTS (
                        SELECT 1 FROM conversion_events ce
                        WHERE ce.sdk_key = b.sdk_key AND ce.event_name = b.event_name
                            AND ce.is_active = 1
                    )
                GROUP BY b.event_name
                """, params);

        List<String> eventNames = new ArrayList<>();
        ruleEvents.forEach(e -> eventNames.add(Values.str(e.get("event_name"))));
        buttonEvents.forEach(e -> eventNames.add(Values.str(e.get("event_name"))));

        Map<String, Map<String, Object>> eventStats = new HashMap<>();
        if (!eventNames.isEmpty()) {
            db.list("""
                    SELECT event_name,
                        count(*) AS event_count,
                        count(DISTINCT client_id) AS unique_users,
                        max(timestamp) AS last_seen
                    FROM events
                    WHERE sdk_key = :sdkKey
                        AND event_name IN (:names)
                        AND timestamp >= :since
                    GROUP BY event_name
                    """, Db.params("sdkKey", user.sdkKey(), "names", eventNames,
                    "since", clock.startOf(clock.today().minusDays(30)))).forEach(stat -> {
                Map<String, Object> s = new LinkedHashMap<>();
                s.put("event_count", stat.get("event_count"));
                s.put("unique_users", stat.get("unique_users"));
                s.put("last_seen", stat.get("last_seen"));
                eventStats.put(Values.str(stat.get("event_name")), s);
            });
        }

        List<Map<String, Object>> availableEvents = new ArrayList<>();
        for (Map<String, Object> event : ruleEvents) {
            Map<String, Object> merged = new LinkedHashMap<>(event);
            merged.putAll(eventStats.getOrDefault(Values.str(event.get("event_name")), Map.of()));
            merged.put("description", "URL 규칙으로 생성 (" + event.get("definition_count") + "개 규칙)");
            availableEvents.add(merged);
        }
        for (Map<String, Object> event : buttonEvents) {
            Map<String, Object> merged = new LinkedHashMap<>(event);
            merged.putAll(eventStats.getOrDefault(Values.str(event.get("event_name")), Map.of()));
            Object first = event.get("descriptions") instanceof List<?> list && !list.isEmpty() ? list.getFirst() : null;
            merged.put("description", first != null && !first.toString().isEmpty()
                    ? first.toString()
                    : "버튼 클릭으로 생성 (" + event.get("definition_count") + "개 설정)");
            availableEvents.add(merged);
        }

        return Map.of("available", availableEvents, "registered", registered);
    }
}
