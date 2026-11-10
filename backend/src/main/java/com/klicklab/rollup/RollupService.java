package com.klicklab.rollup;

import com.klicklab.common.AppClock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * events(원천) → agg_*(집계) 재계산.
 *
 * <p>ClickHouse 의 Materialized View / AggregatingMergeTree 를 대체한다.
 * 하루 단위로 해당 날짜의 집계 행을 지우고 events 로부터 다시 계산하므로 멱등(idempotent)하며,
 * 늦게 도착한 이벤트도 재실행 시 반영된다. 여러 인스턴스가 동시에 실행해도
 * advisory lock 으로 직렬화된다.</p>
 */
@Service
public class RollupService {

    private static final Logger log = LoggerFactory.getLogger(RollupService.class);
    private static final long ADVISORY_LOCK_KEY = 0x4B4C_524F_4C4CL; // "KLROLL"

    private static final List<String> AGG_TABLES = List.of(
            "agg_user_session_daily",
            "agg_user_session_hourly",
            "agg_daily_users",
            "agg_page_daily",
            "agg_event_daily",
            "agg_event_page_daily",
            "agg_traffic_hourly",
            "agg_funnel_links_daily",
            "agg_first_pages_daily",
            "agg_sankey_paths_daily");

    private static final String AGE_GROUP = """
            CASE WHEN e.user_age >= 60 THEN '60s+'
                 WHEN e.user_age >= 50 THEN '50s'
                 WHEN e.user_age >= 40 THEN '40s'
                 WHEN e.user_age >= 30 THEN '30s'
                 WHEN e.user_age >= 20 THEN '20s'
                 WHEN e.user_age >= 10 THEN '10s'
                 ELSE 'unknown' END""";

    /** 하루치 이벤트 + 전환 여부 */
    private static final String CREATE_TMP_EVENTS = """
            CREATE TEMP TABLE tmp_ev ON COMMIT DROP AS
            SELECT e.id, e.sdk_key, e.event_name, e.timestamp,
                   COALESCE(NULLIF(e.client_id, ''), NULLIF(e.user_id, ''), e.session_id, '') AS client_id,
                   COALESCE(e.session_id, '') AS session_id,
                   e.page_path, e.traffic_source, e.traffic_medium, e.traffic_campaign,
                   e.device_type, e.device_os, e.browser, e.city,
                   COALESCE(NULLIF(lower(e.user_gender), ''), 'unknown') AS gender,
                   %s AS age_group,
                   e.time_on_page_seconds, e.properties,
                   (ce.event_name IS NOT NULL) AS is_conversion
              FROM events e
              LEFT JOIN conversion_events ce
                ON ce.sdk_key = e.sdk_key AND ce.event_name = e.event_name AND ce.is_active = 1
             WHERE e.timestamp >= :start AND e.timestamp < :end
            """.formatted(AGE_GROUP);

    /** 세션 단위 요약 (속성은 첫 이벤트, 랜딩/이탈 페이지는 첫/마지막 page_view) */
    private static final String CREATE_TMP_SESSIONS = """
            CREATE TEMP TABLE tmp_sess ON COMMIT DROP AS
            WITH s AS (
                SELECT sdk_key, session_id,
                       min(client_id) AS client_id,
                       min(timestamp) AS started_at,
                       max(timestamp) AS ended_at,
                       count(*) FILTER (WHERE event_name = 'page_view') AS page_views,
                       count(*) FILTER (WHERE is_conversion) AS conversions,
                       COALESCE(sum(CASE WHEN is_conversion AND properties ->> 'value' ~ '^-?[0-9]+(\\.[0-9]+)?$'
                                         THEN (properties ->> 'value')::numeric END), 0) AS conversion_value
                  FROM tmp_ev
                 WHERE session_id <> ''
                 GROUP BY sdk_key, session_id
            ), f AS (
                SELECT DISTINCT ON (sdk_key, session_id)
                       sdk_key, session_id, city, device_type, device_os, browser,
                       traffic_source, traffic_medium, traffic_campaign, gender, age_group
                  FROM tmp_ev
                 WHERE session_id <> ''
                 ORDER BY sdk_key, session_id, timestamp, id
            ), l AS (
                SELECT DISTINCT ON (sdk_key, session_id) sdk_key, session_id, page_path AS landing_page
                  FROM tmp_ev
                 WHERE session_id <> '' AND event_name = 'page_view' AND page_path <> ''
                 ORDER BY sdk_key, session_id, timestamp, id
            ), x AS (
                SELECT DISTINCT ON (sdk_key, session_id) sdk_key, session_id, page_path AS exit_page
                  FROM tmp_ev
                 WHERE session_id <> '' AND event_name = 'page_view' AND page_path <> ''
                 ORDER BY sdk_key, session_id, timestamp DESC, id DESC
            )
            SELECT s.sdk_key, s.session_id, s.client_id, s.page_views, s.conversions, s.conversion_value,
                   extract(hour FROM s.started_at)::smallint AS start_hour,
                   extract(epoch FROM (s.ended_at - s.started_at))::bigint AS duration,
                   f.city, f.device_type, f.device_os, f.browser,
                   f.traffic_source, f.traffic_medium, f.traffic_campaign, f.gender, f.age_group,
                   COALESCE(l.landing_page, '') AS landing_page,
                   COALESCE(x.exit_page, '') AS exit_page
              FROM s
              JOIN f USING (sdk_key, session_id)
              LEFT JOIN l USING (sdk_key, session_id)
              LEFT JOIN x USING (sdk_key, session_id)
            """;

    /** 참여 세션: 10초 이상 체류 또는 2페이지 이상 조회 또는 전환 */
    private static final String ENGAGED = "(duration >= 10 OR page_views >= 2 OR conversions > 0)";

    private static final List<String> INSERTS = List.of(
            """
            INSERT INTO agg_user_session_daily
            SELECT sdk_key, :day, gender, age_group,
                   count(DISTINCT client_id), count(*), COALESCE(sum(duration), 0)
              FROM tmp_sess
             GROUP BY sdk_key, gender, age_group
            """,
            """
            INSERT INTO agg_user_session_hourly
            SELECT sdk_key, :day, start_hour, city, age_group, gender, device_type, device_os, browser,
                   count(DISTINCT client_id), count(*), COALESCE(sum(duration), 0)
              FROM tmp_sess
             GROUP BY sdk_key, start_hour, city, age_group, gender, device_type, device_os, browser
            """,
            """
            INSERT INTO agg_daily_users
            SELECT DISTINCT sdk_key, :day, client_id FROM tmp_ev WHERE client_id <> ''
            """,
            """
            INSERT INTO agg_page_daily
            SELECT e.sdk_key, :day, e.page_path,
                   count(*) FILTER (WHERE e.event_name = 'page_view'),
                   count(DISTINCT e.client_id) FILTER (WHERE e.event_name = 'page_view'),
                   count(DISTINCT e.session_id) FILTER (WHERE e.session_id <> ''),
                   COALESCE(max(x.exits), 0),
                   COALESCE(sum(e.time_on_page_seconds) FILTER (WHERE e.time_on_page_seconds > 0), 0),
                   max(e.timestamp)
              FROM tmp_ev e
              LEFT JOIN (SELECT sdk_key, exit_page, count(*) AS exits
                           FROM tmp_sess WHERE exit_page <> '' GROUP BY sdk_key, exit_page) x
                ON x.sdk_key = e.sdk_key AND x.exit_page = e.page_path
             WHERE e.page_path <> ''
             GROUP BY e.sdk_key, e.page_path
            """,
            """
            INSERT INTO agg_event_daily
            SELECT sdk_key, :day, event_name, count(*), count(DISTINCT client_id)
              FROM tmp_ev WHERE event_name <> ''
             GROUP BY sdk_key, event_name
            """,
            """
            INSERT INTO agg_event_page_daily
            SELECT sdk_key, :day, event_name, page_path, count(*), count(DISTINCT client_id)
              FROM tmp_ev WHERE event_name <> ''
             GROUP BY sdk_key, event_name, page_path
            """,
            """
            INSERT INTO agg_traffic_hourly
            SELECT sdk_key, :day, start_hour, traffic_source, traffic_medium, traffic_campaign, landing_page,
                   count(DISTINCT client_id),
                   count(*),
                   count(*) FILTER (WHERE NOT %1$s),
                   COALESCE(sum(conversions), 0),
                   COALESCE(sum(conversion_value), 0),
                   count(DISTINCT client_id),
                   count(DISTINCT client_id) FILTER (WHERE %1$s),
                   count(DISTINCT client_id) FILTER (WHERE conversions > 0)
              FROM tmp_sess
             GROUP BY sdk_key, start_hour, traffic_source, traffic_medium, traffic_campaign, landing_page
            """.formatted(ENGAGED),
            """
            INSERT INTO agg_funnel_links_daily
            SELECT sdk_key, :day, prev_page, page_path, count(DISTINCT session_id)
              FROM (SELECT sdk_key, session_id, page_path,
                           lag(page_path) OVER (PARTITION BY sdk_key, session_id ORDER BY timestamp, id) AS prev_page
                      FROM tmp_ev
                     WHERE event_name = 'page_view' AND page_path <> '' AND session_id <> '') t
             WHERE prev_page IS NOT NULL AND prev_page <> page_path
             GROUP BY sdk_key, prev_page, page_path
            """,
            """
            INSERT INTO agg_first_pages_daily
            SELECT sdk_key, :day, landing_page, count(*)
              FROM tmp_sess WHERE landing_page <> ''
             GROUP BY sdk_key, landing_page
            """,
            """
            INSERT INTO agg_sankey_paths_daily
            WITH pv AS (
                SELECT sdk_key, session_id, page_path, timestamp, id,
                       lag(page_path) OVER (PARTITION BY sdk_key, session_id ORDER BY timestamp, id) AS prev
                  FROM tmp_ev
                 WHERE event_name = 'page_view' AND page_path <> '' AND session_id <> ''
            ), up AS (
                SELECT sdk_key, session_id,
                       (array_agg(page_path ORDER BY timestamp, id) FILTER (WHERE prev IS DISTINCT FROM page_path))[1 : 20] AS url_path
                  FROM pv GROUP BY sdk_key, session_id
            ), ev AS (
                SELECT sdk_key, session_id, event_name, timestamp, id,
                       lag(event_name) OVER (PARTITION BY sdk_key, session_id ORDER BY timestamp, id) AS prev
                  FROM tmp_ev
                 WHERE session_id <> '' AND event_name <> ''
            ), ep AS (
                SELECT sdk_key, session_id,
                       (array_agg(event_name::text ORDER BY timestamp, id) FILTER (WHERE prev IS DISTINCT FROM event_name))[1 : 20] AS event_path
                  FROM ev GROUP BY sdk_key, session_id
            )
            SELECT ep.sdk_key, :day, ep.session_id, COALESCE(up.url_path, '{}'), ep.event_path
              FROM ep LEFT JOIN up USING (sdk_key, session_id)
             WHERE cardinality(ep.event_path) > 1 OR cardinality(up.url_path) > 1
            """);

    private final NamedParameterJdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final AppClock clock;

    public RollupService(NamedParameterJdbcTemplate jdbc, TransactionTemplate tx, AppClock clock) {
        this.jdbc = jdbc;
        this.tx = tx;
        this.clock = clock;
    }

    /** 지정한 날짜의 모든 집계 테이블을 재계산한다. */
    public void refresh(LocalDate day) {
        long started = System.nanoTime();
        OffsetDateTime start = clock.startOf(day);
        OffsetDateTime end = clock.startOf(day.plusDays(1));
        MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("day", day)
                .addValue("start", start)
                .addValue("end", end);

        tx.executeWithoutResult(status -> {
            jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + ADVISORY_LOCK_KEY + ")");
            jdbc.update(CREATE_TMP_EVENTS, params);
            jdbc.getJdbcTemplate().execute("ANALYZE tmp_ev");
            jdbc.update(CREATE_TMP_SESSIONS, params);
            for (String table : AGG_TABLES) {
                jdbc.update("DELETE FROM " + table + " WHERE summary_date = :day", params);
            }
            for (String insert : INSERTS) {
                jdbc.update(insert.replace(":day", "CAST(:day AS date)"), params);
            }
            long durationMs = (System.nanoTime() - started) / 1_000_000;
            jdbc.update("""
                    INSERT INTO rollup_runs (summary_date, refreshed_at, duration_ms)
                    VALUES (:day, now(), :duration)
                    ON CONFLICT (summary_date) DO UPDATE
                       SET refreshed_at = EXCLUDED.refreshed_at, duration_ms = EXCLUDED.duration_ms
                    """, params.addValue("duration", durationMs));
        });
        log.info("Rollup refreshed for {} in {} ms", day, (System.nanoTime() - started) / 1_000_000);
    }

    /** start ~ end (양끝 포함) 범위를 재계산한다. */
    public void refreshRange(LocalDate start, LocalDate end) {
        for (LocalDate d = start; !d.isAfter(end); d = d.plusDays(1)) {
            refresh(d);
        }
    }

    /** 집계 이력이 없는 날짜 목록 (범위 내) */
    public List<LocalDate> missingDays(LocalDate start, LocalDate end) {
        return jdbc.queryForList("""
                SELECT d::date
                  FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
                 WHERE NOT EXISTS (SELECT 1 FROM rollup_runs r WHERE r.summary_date = d::date)
                 ORDER BY 1
                """, new MapSqlParameterSource().addValue("start", start).addValue("end", end), LocalDate.class);
    }
}
