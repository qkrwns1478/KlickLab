package com.klicklab.report;

import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import com.klicklab.common.Sql;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** KPI 리포트 섹션별 데이터 (컬럼명은 기존 리포트/CSV 헤더와 동일) */
@Service
public class KpiReportService {

    public record Section(String key, String category, List<Map<String, Object>> data) {
    }

    private record Query(String category, String sql) {
    }

    private static final Map<String, Query> QUERIES = new LinkedHashMap<>();

    static {
        QUERIES.put("visitors", new Query("유입 분석: 방문자 수 및 변화 추이", """
                SELECT d::date AS date,
                    COALESCE(a.visitors, 0) AS visitors,
                    COALESCE(a.sessions, 0) AS sessions,
                    round(COALESCE(a.total_duration, 0) / NULLIF(a.sessions, 0), 2) AS avg_session_seconds
                FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
                LEFT JOIN (
                    SELECT summary_date,
                        sum(users) AS visitors,
                        sum(sessions) AS sessions,
                        sum(session_duration_sum) AS total_duration
                    FROM agg_user_session_daily
                    WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    GROUP BY summary_date
                ) a ON a.summary_date = d::date
                ORDER BY 1
                """));
        QUERIES.put("conversions", new Query("전환 분석: 전환 수 및 전환율 변화", """
                SELECT d::date AS date,
                    COALESCE(c.conversions, 0) AS conversions,
                    COALESCE(v.visitors, 0) AS visitors,
                    round(COALESCE(c.conversions, 0) * 100.0 / NULLIF(v.visitors, 0), 2) AS conversion_rate
                FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
                LEFT JOIN (
                    SELECT summary_date, sum(conversions) AS conversions
                    FROM agg_traffic_hourly
                    WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    GROUP BY summary_date
                ) c ON c.summary_date = d::date
                LEFT JOIN (
                    SELECT summary_date, sum(users) AS visitors
                    FROM agg_user_session_daily
                    WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    GROUP BY summary_date
                ) v ON v.summary_date = d::date
                ORDER BY 1
                """));
        QUERIES.put("pages", new Query("페이지 분석: 페이지 조회수 및 체류 시간", """
                SELECT summary_date AS date,
                    page_path,
                    page_views,
                    unique_users AS active_users,
                    round(page_views::numeric / NULLIF(unique_users, 0), 2) AS pageviews_per_user,
                    round((time_on_page_sum / NULLIF(unique_users, 0))::numeric, 2) AS avg_time_on_page
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                ORDER BY date ASC, page_path ASC
                LIMIT 10
                """));
        QUERIES.put("events", new Query("이벤트 분석: 사용자 행동 Top 10", """
                SELECT event_name,
                    sum(event_count) AS total_events,
                    sum(unique_users) AS unique_users,
                    round(sum(event_count) / NULLIF(sum(unique_users), 0), 2) AS avg_per_user
                FROM agg_event_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY event_name
                ORDER BY total_events DESC
                LIMIT 10
                """));
        QUERIES.put("clicks", new Query("클릭 분석: 인기 클릭 세그먼트 Top 10", """
                SELECT summary_date AS date,
                    page_path,
                    sum(event_count) AS total_clicks,
                    sum(unique_users) AS total_users,
                    round(sum(event_count) / NULLIF(sum(unique_users), 0), 2) AS click_rate
                FROM agg_event_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                    AND event_name IN %s
                GROUP BY summary_date, page_path
                ORDER BY total_clicks DESC
                LIMIT 10
                """.formatted(Sql.CLICK_EVENTS)));
        QUERIES.put("bounce", new Query("이탈 분석: 페이지별 이탈률 Top 10", """
                SELECT summary_date AS date,
                    page_path,
                    round(exits * 100.0 / NULLIF(page_views, 0), 1) AS bounce_rate,
                    page_views,
                    exits AS page_exits,
                    round((time_on_page_sum / NULLIF(page_views, 0))::numeric, 1) AS avg_time_on_page_seconds
                FROM agg_page_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                ORDER BY bounce_rate DESC NULLS LAST
                LIMIT 10
                """));
    }

    private final Db db;

    public KpiReportService(Db db) {
        this.db = db;
    }

    public List<Section> build(String sdkKey, DateRange range) {
        var params = range.params(sdkKey);
        return QUERIES.entrySet().stream()
                .map(e -> new Section(e.getKey(), e.getValue().category(), db.list(e.getValue().sql(), params)))
                .toList();
    }
}
