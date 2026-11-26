package com.klicklab.rules;

import com.klicklab.common.Db;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/** 웹사이트에 설치된 SDK 가 인증 없이 규칙을 가져가는 공개 API */
@RestController
@RequestMapping("/api/sdk")
public class SdkController {

    private final Db db;

    public SdkController(Db db) {
        this.db = db;
    }

    @GetMapping("/rules")
    public ResponseEntity<Map<String, Object>> rules(@RequestParam(name = "sdk_key", required = false) String sdkKey) {
        if (sdkKey == null || sdkKey.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "SDK key is required"));
        }
        var params = Db.params("sdkKey", sdkKey);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("eventRules", db.list("SELECT * FROM event_rules WHERE sdk_key = :sdkKey", params));
        body.put("eventbutton", db.list("SELECT * FROM event_button WHERE sdk_key = :sdkKey", params));
        return ResponseEntity.ok(body);
    }
}
