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
import java.util.stream.Stream;

/** URL/이벤트 조건 기반 이벤트 변환 규칙 (대시보드용) */
@RestController
@RequestMapping("/api/rules")
public class EventRuleController {

    public record RuleRequest(String new_event_name, String source_event_name, String condition_type,
                              String condition_parameter, String condition_value) {
    }

    private final Db db;

    public EventRuleController(Db db) {
        this.db = db;
    }

    @GetMapping
    public List<Map<String, Object>> list(@AuthenticationPrincipal AuthUser user) {
        return db.list("SELECT * FROM event_rules WHERE sdk_key = :sdkKey ORDER BY created_at DESC",
                Db.params("sdkKey", user.sdkKey()));
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(@AuthenticationPrincipal AuthUser user,
                                                      @RequestBody RuleRequest body) {
        boolean missing = Stream.of(body.new_event_name(), body.source_event_name(), body.condition_type(),
                body.condition_parameter(), body.condition_value()).anyMatch(v -> v == null || v.isBlank());
        if (missing) {
            return ResponseEntity.badRequest().body(Map.of("error", "All rule fields are required"));
        }
        UUID ruleId = UUID.randomUUID();
        db.update("""
                INSERT INTO event_rules (rule_id, sdk_key, new_event_name, source_event_name,
                                         condition_type, condition_parameter, condition_value)
                VALUES (:ruleId, :sdkKey, :newEvent, :sourceEvent, :type, :param, :value)
                """, Db.params("ruleId", ruleId, "sdkKey", user.sdkKey(),
                "newEvent", body.new_event_name(), "sourceEvent", body.source_event_name(),
                "type", body.condition_type(), "param", body.condition_parameter(), "value", body.condition_value()));
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(Map.of("message", "Event rule created successfully", "rule_id", ruleId.toString()));
    }

    @DeleteMapping("/{ruleId}")
    public Map<String, Object> delete(@AuthenticationPrincipal AuthUser user, @PathVariable String ruleId) {
        db.update("DELETE FROM event_rules WHERE rule_id::text = :ruleId AND sdk_key = :sdkKey",
                Db.params("ruleId", ruleId, "sdkKey", user.sdkKey()));
        return Map.of("message", "Event rule deleted successfully");
    }
}
