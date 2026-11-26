package com.klicklab.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;
import java.time.ZoneId;
import java.util.List;

@ConfigurationProperties(prefix = "klicklab")
public record KlickLabProperties(
        @DefaultValue("Asia/Seoul") ZoneId timezone,
        @DefaultValue Jwt jwt,
        @DefaultValue Cors cors,
        @DefaultValue Auth auth,
        @DefaultValue Rollup rollup) {

    public record Jwt(
            String secret,
            String refreshSecret,
            @DefaultValue("15m") Duration accessTtl,
            @DefaultValue("150m") Duration refreshedAccessTtl,
            @DefaultValue("7d") Duration refreshTtl) {
    }

    public record Cors(@DefaultValue({"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080", "http://127.0.0.1:8080"}) List<String> allowedOrigins) {
    }

    public record Auth(@DefaultValue("false") boolean autoApprove) {
    }

    public record Rollup(
            @DefaultValue("true") boolean enabled,
            @DefaultValue("1h") Duration lateArrivalGrace,
            @DefaultValue("7") int backfillDaysOnStartup) {
    }
}
