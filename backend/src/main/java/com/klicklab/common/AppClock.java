package com.klicklab.common;

import com.klicklab.config.KlickLabProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;

/** 서비스 기준 타임존(기본 Asia/Seoul)의 현재 시각 */
@Component
public class AppClock {

    private final Clock clock;

    @Autowired
    public AppClock(KlickLabProperties properties) {
        this(Clock.system(properties.timezone()));
    }

    public AppClock(Clock clock) {
        this.clock = clock;
    }

    public ZoneId zone() {
        return clock.getZone();
    }

    public ZonedDateTime now() {
        return ZonedDateTime.now(clock);
    }

    public LocalDate today() {
        return LocalDate.now(clock);
    }

    public OffsetDateTime startOf(LocalDate date) {
        return date.atStartOfDay(zone()).toOffsetDateTime();
    }
}
