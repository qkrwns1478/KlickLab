package com.klicklab.common;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;

/** startDate ~ endDate (양끝 포함, yyyy-MM-dd) */
public record DateRange(LocalDate start, LocalDate end) {

    public static final String MISSING_MESSAGE = "Missing startDate or endDate";

    public DateRange {
        if (start.isAfter(end)) {
            LocalDate tmp = start;
            start = end;
            end = tmp;
        }
    }

    /** 둘 다 필수 (없으면 400) */
    public static DateRange required(String start, String end) {
        if (isBlank(start) || isBlank(end)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, MISSING_MESSAGE);
        }
        return new DateRange(parse(start), parse(end));
    }

    /** 없으면 오늘 포함 최근 defaultDays 일 */
    public static DateRange orDefault(String start, String end, AppClock clock, int defaultDays) {
        LocalDate e = isBlank(end) ? clock.today() : parse(end);
        LocalDate s = isBlank(start) ? e.minusDays(defaultDays - 1L) : parse(start);
        return new DateRange(s, e);
    }

    public static LocalDate parse(String value) {
        try {
            // "2025-07-01" 또는 "2025-07-01T00:00:00..." 모두 허용
            return LocalDate.parse(value.trim().length() > 10 ? value.trim().substring(0, 10) : value.trim());
        } catch (DateTimeParseException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid date: " + value);
        }
    }

    /** :sdkKey, :start, :end 바인딩 파라미터 */
    public MapSqlParameterSource params(String sdkKey) {
        return Db.params("sdkKey", sdkKey, "start", start, "end", end);
    }

    public boolean contains(LocalDate date) {
        return !date.isBefore(start) && !date.isAfter(end);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank() || "undefined".equals(s) || "null".equals(s);
    }
}
