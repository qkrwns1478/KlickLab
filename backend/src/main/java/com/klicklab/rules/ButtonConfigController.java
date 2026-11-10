package com.klicklab.rules;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.Db;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 코드리스 클릭 이벤트(CSS selector) 규칙 (대시보드용) */
@RestController
@RequestMapping("/api/buttonConfigs")
public class ButtonConfigController {

    public record ButtonConfigRequest(String event_name, String css_selector, String description) {
    }

    private final Db db;

    public ButtonConfigController(Db db) {
        this.db = db;
    }

    @GetMapping
    public List<Map<String, Object>> list(@AuthenticationPrincipal AuthUser user) {
        return db.list("SELECT * FROM event_button WHERE sdk_key = :sdkKey ORDER BY created_at DESC",
                Db.params("sdkKey", user.sdkKey()));
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(@AuthenticationPrincipal AuthUser user,
                                                      @RequestBody ButtonConfigRequest body) {
        if (isBlank(body.event_name()) || isBlank(body.css_selector())) {
            return ResponseEntity.badRequest().body(Map.of("error", "Event name and CSS selector are required"));
        }
        UUID configId = UUID.randomUUID();
        db.update("""
                INSERT INTO event_button (config_id, sdk_key, event_name, css_selector, description)
                VALUES (:configId, :sdkKey, :eventName, :selector, :description)
                """, Db.params("configId", configId, "sdkKey", user.sdkKey(), "eventName", body.event_name(),
                "selector", body.css_selector(), "description", body.description() == null ? "" : body.description()));
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(Map.of("message", "event config created", "config_id", configId.toString()));
    }

    @DeleteMapping("/{configId}")
    public Map<String, Object> delete(@AuthenticationPrincipal AuthUser user, @PathVariable String configId) {
        db.update("DELETE FROM event_button WHERE config_id::text = :configId AND sdk_key = :sdkKey",
                Db.params("configId", configId, "sdkKey", user.sdkKey()));
        return Map.of("message", "Codeless event config deleted");
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
