package com.klicklab.aggregation;

import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.Period;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAmount;

/**
 * 집계 구간 단위. 테이블 접두어(minutes_, hourly_, daily_, weekly_)와 구간 길이, 상위 집계의 원천 단위를 정의한다.
 */
public enum Granularity {

    MINUTES("minutes", Duration.ofMinutes(10)),
    HOURLY("hourly", Duration.ofHours(1)),
    DAILY("daily", Period.ofDays(1)),
    WEEKLY("weekly", Period.ofDays(7));

    private final String prefix;
    private final TemporalAmount length;

    Granularity(String prefix, TemporalAmount length) {
        this.prefix = prefix;
        this.length = length;
    }

    public String prefix() {
        return prefix;
    }

    public String table(String suffix) {
        return prefix + "_" + suffix;
    }

    /** 구간을 나타내는 컬럼: 시각 단위는 date_time(timestamptz), 날짜 단위는 date(date) */
    public String bucketColumn() {
        return isDateBased() ? "date" : "date_time";
    }

    public boolean isDateBased() {
        return this == DAILY || this == WEEKLY;
    }

    /** 바로 아래 단위 (상위 집계의 원천) */
    public Granularity child() {
        return switch (this) {
            case MINUTES -> throw new IllegalStateException("minutes 는 events 로부터 집계한다");
            case HOURLY -> MINUTES;
            case DAILY -> HOURLY;
            case WEEKLY -> DAILY;
        };
    }

    public LocalDateTime end(LocalDateTime start) {
        return start.plus(length);
    }

    /** 주어진 시각이 속한 구간의 시작. 주간은 임의의 날짜에서 시작할 수 있으므로 날짜만 맞춘다. */
    public LocalDateTime align(LocalDateTime time) {
        return switch (this) {
            case MINUTES -> time.truncatedTo(ChronoUnit.HOURS).plusMinutes(time.getMinute() / 10 * 10L);
            case HOURLY -> time.truncatedTo(ChronoUnit.HOURS);
            case DAILY, WEEKLY -> time.truncatedTo(ChronoUnit.DAYS);
        };
    }

    /** now 기준 직전에 끝난 구간의 시작 (주간은 지난 7일) */
    public LocalDateTime previous(LocalDateTime now) {
        return switch (this) {
            case MINUTES, HOURLY, DAILY -> align(now).minus(length);
            case WEEKLY -> now.truncatedTo(ChronoUnit.DAYS).minusDays(7);
        };
    }

    /** 스케줄 시점: 매 10분 / 정각 / 매일 00:10 / 매주 월요일 00:30 */
    public boolean isDueAt(LocalDateTime tick) {
        int minute = tick.getMinute();
        int hour = tick.getHour();
        return switch (this) {
            case MINUTES -> minute % 10 == 0;
            case HOURLY -> minute == 0;
            case DAILY -> hour == 0 && minute == 10;
            case WEEKLY -> tick.getDayOfWeek() == DayOfWeek.MONDAY && hour == 0 && minute == 30;
        };
    }
}
