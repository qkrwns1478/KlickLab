package com.klicklab.traffic;

import com.klicklab.common.AppClock;
import com.klicklab.common.Db;
import com.klicklab.common.Values;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.stereotype.Service;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.YearMonth;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static com.klicklab.common.Maps.obj;

/** Traffic 탭 통합 데이터 */
@Service
public class TrafficService {

    private static final long CACHE_TTL_MS = 60_000;
    private static final DateTimeFormatter HOUR_LABEL = DateTimeFormatter.ofPattern("yyyy-MM-dd HH");
    private static final DateTimeFormatter MONTH_LABEL = DateTimeFormatter.ofPattern("yyyy-MM");

    public record Filters(String sdkKey, String period, String gender, String ageGroup) {
        String cacheKey() {
            return sdkKey + "|" + period + "|" + gender + "|" + ageGroup;
        }
    }

    private record CacheEntry(Map<String, Object> data, long createdAt) {
    }

    private final Db db;
    private final AppClock clock;
    private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public TrafficService(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    public Map<String, Object> dashboard(Filters f) {
        long now = System.currentTimeMillis();
        CacheEntry cached = cache.get(f.cacheKey());
        if (cached != null && now - cached.createdAt() < CACHE_TTL_MS) {
            return cached.data();
        }
        cache.values().removeIf(e -> now - e.createdAt() >= CACHE_TTL_MS);
        Map<String, Object> data = buildDashboard(f);
        cache.put(f.cacheKey(), new CacheEntry(data, now));
        return data;
    }

    private Map<String, Object> buildDashboard(Filters f) {
        ZonedDateTime now = clock.now();
        ZonedDateTime[] range = periodRange(f.period(), now);
        MapSqlParameterSource clickParams = Db.params("sdkKey", f.sdkKey(),
                "start", range[0].toOffsetDateTime(), "end", range[1].toOffsetDateTime(),
                "gender", f.gender(), "ageGroup", f.ageGroup());
        String clickWhere = clickWhere(f);

        List<Map<String, Object>> hourlyRows = db.list("""
                SELECT to_char(timestamp, 'HH24') AS hour, count(*) AS visitors
                  FROM events WHERE %s
                 GROUP BY 1
                """.formatted(clickWhere), clickParams);
        Map<String, Long> byHour = new HashMap<>();
        hourlyRows.forEach(r -> byHour.put(Values.str(r.get("hour")), Values.toLong(r.get("visitors"))));
        List<Map<String, Object>> hourlyTraffic = new ArrayList<>(24);
        for (int h = 0; h < 24; h++) {
            String hour = String.format("%02d", h);
            hourlyTraffic.add(obj("hour", hour, "visitors", byHour.getOrDefault(hour, 0L)));
        }

        MapSqlParameterSource periodParams = periodParams(f.sdkKey(), f.period(), now);
        String periodWhere = "sdk_key = :sdkKey AND event_name = 'auto_click' AND timestamp >= :pStart AND timestamp < :pEnd";

        List<Map<String, Object>> mainPageNav = db.list("""
                SELECT page_path AS page, count(*) AS clicks, count(DISTINCT user_id) AS unique_clicks
                  FROM events WHERE %s AND page_path <> '/'
                 GROUP BY page_path
                 ORDER BY clicks DESC
                 LIMIT 10
                """.formatted(periodWhere), periodParams);
        List<Map<String, Object>> mainPageNavigation = new ArrayList<>();
        for (int i = 0; i < mainPageNav.size(); i++) {
            Map<String, Object> r = mainPageNav.get(i);
            mainPageNavigation.add(obj(
                    "name", r.get("page"), "page", r.get("page"),
                    "clicks", Values.toLong(r.get("clicks")), "uniqueClicks", Values.toLong(r.get("unique_clicks")),
                    "clickRate", 0, "avgTimeToClick", 0, "rank", i + 1, "id", String.valueOf(i + 1)));
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("visitorTrend", visitorTrend(f, now));
        body.put("mainPageNavigation", mainPageNavigation);
        body.put("hourlyTraffic", hourlyTraffic);
        body.put("entryPageDistribution", distribution("traffic_source", "source", periodWhere, periodParams));
        body.put("mediumDistribution", distribution("traffic_medium", "medium", clickWhere, clickParams));
        body.put("campaignDistribution", distribution("traffic_campaign", "campaign", clickWhere, clickParams));
        body.put("referrerDistribution", distribution("referrer", "referrer", clickWhere, clickParams));
        body.put("filters", obj("period", f.period(), "gender", f.gender(), "ageGroup", f.ageGroup()));
        return body;
    }

    /** 방문자 추이 (period: hourly | daily | weekly | monthly) */
    public List<Map<String, Object>> visitorTrend(Filters f, ZonedDateTime now) {
        LocalDate today = now.toLocalDate();
        String segmentFilter = ("all".equals(f.gender()) ? "" : " AND gender = :gender")
                + ("all".equals(f.ageGroup()) ? "" : " AND age_group = :ageGroup");

        switch (f.period()) {
            case "hourly" -> {
                ZonedDateTime firstHour = now.truncatedTo(ChronoUnit.HOURS).minusHours(23);
                Map<String, Long> values = toMap(db.list("""
                        SELECT to_char(summary_date + make_interval(hours => summary_hour), 'YYYY-MM-DD HH24') AS label,
                               sum(users) AS visitors
                          FROM agg_user_session_hourly
                         WHERE sdk_key = :sdkKey AND summary_date BETWEEN :startDate AND :endDate
                           AND summary_date + make_interval(hours => summary_hour) >= :since %s
                         GROUP BY 1
                        """.formatted(segmentFilter), Db.params("sdkKey", f.sdkKey(),
                        "startDate", firstHour.toLocalDate(), "endDate", today,
                        "since", firstHour.toLocalDateTime(), "gender", f.gender(), "ageGroup", f.ageGroup())));
                List<String> labels = new ArrayList<>();
                for (int i = 0; i < 24; i++) {
                    labels.add(firstHour.plusHours(i).format(HOUR_LABEL));
                }
                return fill(labels, values);
            }
            case "weekly" -> {
                LocalDate thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
                Map<String, Long> values = new HashMap<>();
                dailyVisitors(f, segmentFilter, thisMonday.minusWeeks(5), thisMonday.plusDays(6))
                        .forEach((date, v) -> values.merge(weekLabel(date), v, Long::sum));
                List<String> labels = new ArrayList<>();
                for (int i = 5; i >= 0; i--) {
                    labels.add(weekLabel(today.minusWeeks(i)));
                }
                return fill(labels, values);
            }
            case "monthly" -> {
                YearMonth thisMonth = YearMonth.from(today);
                Map<String, Long> values = new HashMap<>();
                dailyVisitors(f, segmentFilter, thisMonth.minusMonths(11).atDay(1), thisMonth.atEndOfMonth())
                        .forEach((date, v) -> values.merge(date.format(MONTH_LABEL), v, Long::sum));
                List<String> labels = new ArrayList<>();
                for (int i = 11; i >= 0; i--) {
                    labels.add(thisMonth.minusMonths(i).format(MONTH_LABEL));
                }
                return fill(labels, values);
            }
            default -> {
                // daily: 오늘 포함 최근 7일 (데이터가 있는 날짜만)
                Map<LocalDate, Long> values = dailyVisitors(f, segmentFilter, today.minusDays(6), today);
                return values.entrySet().stream()
                        .map(e -> trendRow(e.getKey().toString(), e.getValue()))
                        .toList();
            }
        }
    }

    /** 일별 방문자 (정렬된 Map) */
    private Map<LocalDate, Long> dailyVisitors(Filters f, String segmentFilter, LocalDate start, LocalDate end) {
        Map<LocalDate, Long> result = new LinkedHashMap<>();
        db.list("""
                SELECT summary_date, sum(users) AS visitors
                  FROM agg_user_session_daily
                 WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end %s
                 GROUP BY summary_date
                 ORDER BY summary_date
                """.formatted(segmentFilter), Db.params("sdkKey", f.sdkKey(), "start", start, "end", end,
                        "gender", f.gender(), "ageGroup", f.ageGroup()))
                .forEach(r -> result.put(LocalDate.parse(Values.str(r.get("summary_date"))),
                        Values.toLong(r.get("visitors"))));
        return result;
    }

    private List<Map<String, Object>> distribution(String column, String key, String where,
                                                   MapSqlParameterSource params) {
        return db.list("""
                SELECT %1$s AS value, count(*) AS visitors
                  FROM events WHERE %2$s
                 GROUP BY %1$s
                 ORDER BY visitors DESC
                 LIMIT 10
                """.formatted(column, where), params).stream().map(r -> {
            String value = Values.str(r.get("value"));
            return obj(key, value.isEmpty() ? "(없음)" : value, "visitors", Values.toLong(r.get("visitors")));
        }).toList();
    }

    /** 성별/연령 필터가 적용된 클릭 이벤트 조건 */
    private static String clickWhere(Filters f) {
        StringBuilder where = new StringBuilder(
                "sdk_key = :sdkKey AND event_name = 'auto_click' AND timestamp >= :start AND timestamp <= :end");
        if (!"all".equals(f.gender())) {
            where.append(" AND user_gender = :gender");
        }
        String age = ageCondition(f.ageGroup());
        if (!age.isEmpty()) {
            where.append(" AND ").append(age);
        }
        return where.toString();
    }

    static String ageCondition(String ageGroup) {
        return switch (ageGroup) {
            case "10s" -> "user_age >= 10 AND user_age < 20";
            case "20s" -> "user_age >= 20 AND user_age < 30";
            case "30s" -> "user_age >= 30 AND user_age < 40";
            case "40s" -> "user_age >= 40 AND user_age < 50";
            case "50s" -> "user_age >= 50 AND user_age < 60";
            case "60s+" -> "user_age >= 60";
            default -> "";
        };
    }

    /** 성별/연령 필터 조회 기간 */
    static ZonedDateTime[] periodRange(String period, ZonedDateTime now) {
        LocalDate today = now.toLocalDate();
        return switch (period) {
            case "weekly" -> {
                LocalDate thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
                yield new ZonedDateTime[]{
                        thisMonday.minusWeeks(5).atStartOfDay(now.getZone()),
                        thisMonday.plusDays(7).atStartOfDay(now.getZone()).minusNanos(1)};
            }
            case "monthly" -> {
                YearMonth thisMonth = YearMonth.from(today);
                yield new ZonedDateTime[]{
                        thisMonth.minusMonths(11).atDay(1).atStartOfDay(now.getZone()),
                        thisMonth.plusMonths(1).atDay(1).atStartOfDay(now.getZone()).minusNanos(1)};
            }
            default -> new ZonedDateTime[]{now.minusDays(6), now};
        };
    }

    /** 유입 소스/메인 페이지 탐색용 기간: 어제 / 최근 1시간 / 지난주 / 지난달 */
    private MapSqlParameterSource periodParams(String sdkKey, String period, ZonedDateTime now) {
        LocalDate today = now.toLocalDate();
        LocalDateTime start;
        LocalDateTime end;
        switch (period) {
            case "hourly" -> {
                start = now.minusHours(1).toLocalDateTime();
                end = now.toLocalDateTime();
            }
            case "weekly" -> {
                LocalDate thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
                start = thisMonday.minusWeeks(1).atStartOfDay();
                end = thisMonday.atStartOfDay();
            }
            case "monthly" -> {
                LocalDate firstOfMonth = today.withDayOfMonth(1);
                start = firstOfMonth.minusMonths(1).atStartOfDay();
                end = firstOfMonth.atStartOfDay();
            }
            default -> {
                start = today.minusDays(1).atStartOfDay();
                end = today.atStartOfDay();
            }
        }
        return Db.params("sdkKey", sdkKey,
                "pStart", start.atZone(now.getZone()).toOffsetDateTime(),
                "pEnd", end.atZone(now.getZone()).toOffsetDateTime());
    }

    /** "MM월 N주차" (월요일 시작 주 기준) */
    static String weekLabel(LocalDate date) {
        int firstDayOfWeek = date.withDayOfMonth(1).getDayOfWeek().getValue(); // Mon=1 .. Sun=7
        int weekOfMonth = (int) Math.ceil((date.getDayOfMonth() + firstDayOfWeek - 1) / 7.0);
        return String.format("%02d월 %d주차", date.getMonthValue(), weekOfMonth);
    }

    private static Map<String, Long> toMap(List<Map<String, Object>> rows) {
        Map<String, Long> map = new HashMap<>();
        rows.forEach(r -> map.put(Values.str(r.get("label")), Values.toLong(r.get("visitors"))));
        return map;
    }

    private static List<Map<String, Object>> fill(List<String> labels, Map<String, Long> values) {
        return labels.stream().map(l -> trendRow(l, values.getOrDefault(l, 0L))).toList();
    }

    private static Map<String, Object> trendRow(String date, long visitors) {
        return obj("date", date, "visitors", visitors, "newVisitors", 0, "returningVisitors", 0);
    }
}
