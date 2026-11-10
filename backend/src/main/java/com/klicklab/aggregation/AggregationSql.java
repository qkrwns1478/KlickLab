package com.klicklab.aggregation;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 집계 SQL (klicklab-workers 의 insert*.js 쿼리를 PostgreSQL 로 이식).
 *
 * <p>모든 쿼리는 한 구간만 다룬다. 바인드 파라미터:
 * {@code :bucket}(구간 시작, 단위에 따라 timestamptz/date), {@code :start}/{@code :end}(구간 시각, 반열림),
 * {@code :startDate}/{@code :endDate}(구간 날짜, 반열림), {@code :segmentType}.</p>
 */
public final class AggregationSql {

    /** SQL 과 해당 SQL 에만 필요한 추가 파라미터 */
    public record Statement(String sql, Map<String, Object> params) {
        Statement(String sql) {
            this(sql, Map.of());
        }
    }

    record Segment(String type, String expr) {
    }

    static final String AGE_GROUP = """
            CASE WHEN user_age BETWEEN 10 AND 19 THEN '10s'
                 WHEN user_age BETWEEN 20 AND 29 THEN '20s'
                 WHEN user_age BETWEEN 30 AND 39 THEN '30s'
                 WHEN user_age BETWEEN 40 AND 49 THEN '40s'
                 WHEN user_age BETWEEN 50 AND 59 THEN '50s'
                 WHEN user_age >= 60 THEN '60s+'
                 ELSE 'unknown' END""";

    /** 기존 config/segmentList.js */
    static final List<Segment> SEGMENTS = List.of(
            new Segment("user_gender", "user_gender"),
            new Segment("traffic_source", "traffic_source"),
            new Segment("device_type", "device_type"),
            new Segment("user_age", AGE_GROUP));

    private static final String EVENTS_IN_BUCKET = "timestamp >= :start AND timestamp < :end";

    private AggregationSql() {
    }

    public static String delete(Granularity g, AggregationTarget target) {
        return "DELETE FROM " + g.table(target.suffix()) + " WHERE " + g.bucketColumn() + " = " + bucket(g);
    }

    public static List<Statement> inserts(Granularity g, AggregationTarget target) {
        boolean fromEvents = target.readsEvents(g);
        return switch (target) {
            case METRICS -> List.of(new Statement(fromEvents ? metricsFromEvents(g) : metricsRollup(g)));
            case CLICK_SUMMARY -> fromEvents
                    ? perSegment(segment -> clickSummaryFromEvents(g, segment))
                    : List.of(new Statement(clickSummaryRollup(g)));
            case TOP_ELEMENTS -> fromEvents
                    ? perSegment(segment -> topElementsFromEvents(g, segment))
                    : List.of(new Statement(topElementsRollup(g)));
            case USER_DISTRIBUTION -> fromEvents
                    ? perSegment(segment -> userDistributionFromEvents(g, segment))
                    : List.of(new Statement(userDistributionRollup(g)));
            case PAGE_STATS -> List.of(new Statement(fromEvents ? pageStatsFromEvents(g) : pageStatsRollup(g)));
        };
    }

    private interface SegmentSql {
        List<String> build(Segment segment);
    }

    private static List<Statement> perSegment(SegmentSql builder) {
        List<Statement> statements = new ArrayList<>();
        for (Segment segment : SEGMENTS) {
            for (String sql : builder.build(segment)) {
                statements.add(new Statement(sql, Map.of("segmentType", segment.type())));
            }
        }
        return statements;
    }

    private static String bucket(Granularity g) {
        return g.isDateBased() ? "CAST(:bucket AS date)" : "CAST(:bucket AS timestamptz)";
    }

    /** 원천(아래 단위) 테이블에서 구간에 해당하는 행 */
    private static String childInBucket(Granularity g) {
        return g.child().isDateBased()
                ? "date >= :startDate AND date < :endDate"
                : "date_time >= :start AND date_time < :end";
    }

    private static String columns(Granularity g, String columns) {
        return g.bucketColumn() + ", " + columns;
    }

    // -----------------------------------------------------------------
    // metrics (insertMM / insertHM / insertDM / insertWM)
    // -----------------------------------------------------------------

    /** 신규 방문자: 구간 시작 이전에 이벤트가 없는 client_id. 세션 시간: client 별 구간 내 첫~마지막 이벤트 간격 */
    private static String metricsFromEvents(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                WITH w AS (
                    SELECT sdk_key, client_id, event_name,
                        extract(epoch FROM max(timestamp) OVER c - min(timestamp) OVER c)::bigint AS session_seconds
                    FROM events
                    WHERE %4$s
                    WINDOW c AS (PARTITION BY sdk_key, client_id)
                ), visitor AS (
                    SELECT v.sdk_key,
                        EXISTS (
                            SELECT 1
                            FROM events p
                            WHERE p.sdk_key = v.sdk_key AND p.client_id = v.client_id AND p.timestamp < :start
                        ) AS is_existing
                    FROM (
                        SELECT DISTINCT sdk_key, client_id
                        FROM w
                        WHERE client_id IS NOT NULL
                    ) v
                )
                SELECT %3$s, m.sdk_key, m.clicks, m.visitors,
                    COALESCE(v.new_visitors, 0), COALESCE(v.existing_visitors, 0), m.avg_session_seconds
                FROM (
                    SELECT sdk_key,
                        count(*) FILTER (WHERE event_name = 'auto_click') AS clicks,
                        count(DISTINCT client_id) AS visitors,
                        COALESCE(trunc(avg(session_seconds) FILTER (WHERE session_seconds > 0)), 0) AS avg_session_seconds
                    FROM w
                    GROUP BY sdk_key
                ) m
                LEFT JOIN (
                    SELECT sdk_key,
                        count(*) FILTER (WHERE NOT is_existing) AS new_visitors,
                        count(*) FILTER (WHERE is_existing) AS existing_visitors
                    FROM visitor
                    GROUP BY sdk_key
                ) v USING (sdk_key)
                """.formatted(g.table("metrics"),
                columns(g, "sdk_key, clicks, visitors, new_visitors, existing_visitors, avg_session_seconds"),
                bucket(g), EVENTS_IN_BUCKET);
    }

    private static String metricsRollup(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, sum(clicks), sum(visitors), sum(new_visitors), sum(existing_visitors),
                    COALESCE(trunc(avg(avg_session_seconds)), 0)
                FROM %4$s
                WHERE %5$s
                GROUP BY sdk_key
                """.formatted(g.table("metrics"),
                columns(g, "sdk_key, clicks, visitors, new_visitors, existing_visitors, avg_session_seconds"),
                bucket(g), g.child().table("metrics"), childInBucket(g));
    }

    // -----------------------------------------------------------------
    // click_summary (insert*U.js 1번)
    // -----------------------------------------------------------------

    private static List<String> clickSummaryFromEvents(Granularity g, Segment segment) {
        return List.of("""
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, :segmentType, segment_value,
                    count(*), count(DISTINCT client_id),
                    round(count(*)::numeric / NULLIF(count(DISTINCT client_id), 0), 1)
                FROM (
                    SELECT sdk_key, client_id, %4$s AS segment_value
                    FROM events
                    WHERE event_name = 'auto_click' AND %5$s
                ) e
                WHERE segment_value IS NOT NULL
                GROUP BY sdk_key, segment_value
                """.formatted(g.table("click_summary"),
                columns(g, "sdk_key, segment_type, segment_value, total_clicks, total_users, avg_clicks_per_user"),
                bucket(g), segment.expr(), EVENTS_IN_BUCKET));
    }

    private static String clickSummaryRollup(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, segment_type, segment_value,
                    sum(total_clicks), sum(total_users),
                    round(sum(total_clicks) / NULLIF(sum(total_users), 0), 1)
                FROM %4$s
                WHERE %5$s
                GROUP BY sdk_key, segment_type, segment_value
                """.formatted(g.table("click_summary"),
                columns(g, "sdk_key, segment_type, segment_value, total_clicks, total_users, avg_clicks_per_user"),
                bucket(g), g.child().table("click_summary"), childInBucket(g));
    }

    // -----------------------------------------------------------------
    // top_elements (insert*U.js 2번): 세그먼트 값별 클릭 수 상위 3개 요소
    // -----------------------------------------------------------------

    private static List<String> topElementsFromEvents(Granularity g, Segment segment) {
        return List.of("""
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, :segmentType, segment_value, rank, element, total_clicks, user_count
                FROM (
                    SELECT sdk_key, segment_value, element,
                        count(*) AS total_clicks,
                        count(DISTINCT client_id) AS user_count,
                        row_number() OVER (PARTITION BY sdk_key, segment_value ORDER BY count(*) DESC, element) AS rank
                    FROM (
                        SELECT sdk_key, client_id, element, %4$s AS segment_value
                        FROM events
                        WHERE event_name = 'auto_click' AND %5$s AND element <> ''
                    ) e
                    WHERE segment_value IS NOT NULL
                    GROUP BY sdk_key, segment_value, element
                ) ranked
                WHERE rank <= 3
                """.formatted(g.table("top_elements"),
                columns(g, "sdk_key, segment_type, segment_value, rank, element, total_clicks, user_count"),
                bucket(g), segment.expr(), EVENTS_IN_BUCKET));
    }

    private static String topElementsRollup(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, segment_type, segment_value, rank, element, total_clicks, user_count
                FROM (
                    SELECT sdk_key, segment_type, segment_value, element,
                        sum(total_clicks) AS total_clicks,
                        sum(user_count) AS user_count,
                        row_number() OVER (
                            PARTITION BY sdk_key, segment_type, segment_value
                            ORDER BY sum(total_clicks) DESC, element
                        ) AS rank
                    FROM %4$s
                    WHERE %5$s
                    GROUP BY sdk_key, segment_type, segment_value, element
                ) ranked
                WHERE rank <= 3
                """.formatted(g.table("top_elements"),
                columns(g, "sdk_key, segment_type, segment_value, rank, element, total_clicks, user_count"),
                bucket(g), g.child().table("top_elements"), childInBucket(g));
    }

    // -----------------------------------------------------------------
    // user_distribution (insert*U.js 3번): 세그먼트 값별 연령대 / 기기 분포
    // -----------------------------------------------------------------

    private static List<String> userDistributionFromEvents(Granularity g, Segment segment) {
        String template = """
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, :segmentType, segment_value, '%6$s', dist_value, count(DISTINCT client_id)
                FROM (
                    SELECT sdk_key, client_id, %4$s AS segment_value, %7$s AS dist_value
                    FROM events
                    WHERE event_name = 'auto_click' AND %5$s AND %8$s
                ) e
                WHERE segment_value IS NOT NULL
                GROUP BY sdk_key, segment_value, dist_value
                """;
        String table = g.table("user_distribution");
        String cols = columns(g, "sdk_key, segment_type, segment_value, dist_type, dist_value, user_count");
        return List.of(
                template.formatted(table, cols, bucket(g), segment.expr(), EVENTS_IN_BUCKET,
                        "ageGroup", AGE_GROUP, "user_age IS NOT NULL"),
                template.formatted(table, cols, bucket(g), segment.expr(), EVENTS_IN_BUCKET,
                        "device", "device_type", "device_type <> ''"));
    }

    private static String userDistributionRollup(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                SELECT %3$s, sdk_key, segment_type, segment_value, dist_type, dist_value, sum(user_count)
                FROM %4$s
                WHERE %5$s
                GROUP BY sdk_key, segment_type, segment_value, dist_type, dist_value
                """.formatted(g.table("user_distribution"),
                columns(g, "sdk_key, segment_type, segment_value, dist_type, dist_value, user_count"),
                bucket(g), g.child().table("user_distribution"), childInBucket(g));
    }

    // -----------------------------------------------------------------
    // page_stats (insertMP / insertHP / insertDP / insertWP)
    // -----------------------------------------------------------------

    /** 세션 내 다음 이벤트의 페이지가 없으면 이탈. next_pages 는 다음 페이지별 이동 횟수 */
    private static String pageStatsFromEvents(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                WITH base AS (
                    SELECT sdk_key, page_path, time_on_page_seconds,
                        lead(page_path) OVER (PARTITION BY sdk_key, session_id ORDER BY timestamp, id) AS next_page
                    FROM events
                    WHERE %4$s AND page_path <> ''
                ), pages AS (
                    SELECT sdk_key, page_path,
                        count(*) AS page_views,
                        count(*) FILTER (WHERE next_page IS NULL) AS page_exits,
                        round(avg(time_on_page_seconds)::numeric, 2) AS avg_time
                    FROM base
                    GROUP BY sdk_key, page_path
                ), transitions AS (
                    SELECT sdk_key, page_path,
                        jsonb_agg(jsonb_build_object('to', next_page, 'count', moves) ORDER BY moves DESC, next_page) AS next_pages
                    FROM (
                        SELECT sdk_key, page_path, next_page, count(*) AS moves
                        FROM base
                        WHERE next_page IS NOT NULL
                        GROUP BY sdk_key, page_path, next_page
                    ) t
                    GROUP BY sdk_key, page_path
                )
                SELECT %3$s, p.sdk_key, p.page_path, p.page_views, p.page_exits,
                    round(p.page_exits::numeric / p.page_views, 3),
                    COALESCE(t.next_pages, '[]'::jsonb), p.avg_time
                FROM pages p
                LEFT JOIN transitions t USING (sdk_key, page_path)
                """.formatted(g.table("page_stats"), pageStatsColumns(g), bucket(g), EVENTS_IN_BUCKET);
    }

    /** 조회/이탈 수는 합산, next_pages 는 페이지별 이동 횟수를 합산, 평균 체류 시간은 하위 구간 평균의 평균 */
    private static String pageStatsRollup(Granularity g) {
        return """
                INSERT INTO %1$s (%2$s)
                WITH src AS (
                    SELECT sdk_key, page_path, page_views, page_exits, next_pages, avg_time_on_page_seconds
                    FROM %4$s
                    WHERE %5$s
                ), pages AS (
                    SELECT sdk_key, page_path,
                        sum(page_views) AS page_views,
                        sum(page_exits) AS page_exits,
                        round(avg(avg_time_on_page_seconds)::numeric, 2) AS avg_time
                    FROM src
                    GROUP BY sdk_key, page_path
                ), transitions AS (
                    SELECT sdk_key, page_path,
                        jsonb_agg(jsonb_build_object('to', next_page, 'count', moves) ORDER BY moves DESC, next_page) AS next_pages
                    FROM (
                        SELECT s.sdk_key, s.page_path, n ->> 'to' AS next_page, sum((n ->> 'count')::bigint) AS moves
                        FROM src s
                        CROSS JOIN LATERAL jsonb_array_elements(s.next_pages) n
                        GROUP BY s.sdk_key, s.page_path, n ->> 'to'
                    ) t
                    GROUP BY sdk_key, page_path
                )
                SELECT %3$s, p.sdk_key, p.page_path, p.page_views, p.page_exits,
                    CASE WHEN p.page_views = 0 THEN 0 ELSE round(p.page_exits / p.page_views, 3) END,
                    COALESCE(t.next_pages, '[]'::jsonb), p.avg_time
                FROM pages p
                LEFT JOIN transitions t USING (sdk_key, page_path)
                """.formatted(g.table("page_stats"), pageStatsColumns(g), bucket(g),
                g.child().table("page_stats"), childInBucket(g));
    }

    private static String pageStatsColumns(Granularity g) {
        return columns(g, "sdk_key, page_path, page_views, page_exits, drop_rate, next_pages, avg_time_on_page_seconds");
    }
}
