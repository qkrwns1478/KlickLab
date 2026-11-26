package com.klicklab.settings;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.Db;
import com.klicklab.common.JsonText;
import com.klicklab.common.Values;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/settings")
public class SettingsController {

    static final List<String> AVAILABLE_EVENTS = List.of("is_payment", "is_signup", "add_to_cart", "contact_submit");
    static final String DEFAULT_EVENT = "is_payment";

    public record EventRequest(String event) {
    }

    public record DomainRequest(String domain) {
    }

    private final Db db;

    public SettingsController(Db db) {
        this.db = db;
    }

    @GetMapping("/get-key")
    public ResponseEntity<String> getKey(@AuthenticationPrincipal AuthUser user) {
        return JsonText.ok(user.sdkKey());
    }

    @GetMapping("/conversion-events")
    public Map<String, Object> conversionEvents() {
        return Map.of("events", AVAILABLE_EVENTS);
    }

    @GetMapping("/current-conversion-event")
    public Map<String, Object> currentConversionEvent(@AuthenticationPrincipal AuthUser user) {
        Object event = db.one("SELECT event FROM users WHERE sdk_key = :sdkKey",
                Db.params("sdkKey", user.sdkKey())).get("event");
        String current = event == null || event.toString().isBlank() ? DEFAULT_EVENT : event.toString();
        return Map.of("currentEvent", current);
    }

    @PostMapping("/conversion-event")
    public ResponseEntity<Map<String, Object>> setConversionEvent(@AuthenticationPrincipal AuthUser user,
                                                                  @RequestBody EventRequest body) {
        if (body.event() == null || !AVAILABLE_EVENTS.contains(body.event())) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "유효하지 않은 이벤트입니다."));
        }
        db.update("UPDATE users SET event = :event, updated_at = now() WHERE sdk_key = :sdkKey",
                Db.params("event", body.event(), "sdkKey", user.sdkKey()));
        return ResponseEntity.ok(Map.of("success", true, "currentEvent", body.event()));
    }

    @GetMapping("/get-domain")
    public Map<String, Object> getDomain(@AuthenticationPrincipal AuthUser user) {
        var params = Db.params("sdkKey", user.sdkKey());
        Object domainValue = db.one("SELECT domain FROM users WHERE sdk_key = :sdkKey", params).get("domain");
        String domain = domainValue == null || domainValue.toString().isBlank() ? "-" : domainValue.toString();

        long eventCount = db.longValue(
                "SELECT COALESCE(sum(page_views), 0) FROM agg_page_daily WHERE sdk_key = :sdkKey", params);
        Object latest = db.one("SELECT max(timestamp) AS latest FROM events WHERE sdk_key = :sdkKey", params)
                .get("latest");

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("domain", domain);
        body.put("status", "-".equals(domain) ? "inactive" : "active");
        body.put("lastEvent", latest == null ? "-" : Values.str(latest));
        body.put("eventCount", eventCount);
        return body;
    }

    @PostMapping("/update-domain")
    public ResponseEntity<String> updateDomain(@AuthenticationPrincipal AuthUser user,
                                               @RequestBody DomainRequest body) {
        db.update("UPDATE users SET domain = :domain, updated_at = now() WHERE sdk_key = :sdkKey",
                Db.params("domain", body.domain(), "sdkKey", user.sdkKey()));
        return JsonText.ok(body.domain());
    }
}
