package com.klicklab.aggregation;

import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GranularityTest {

    static final LocalDateTime T = LocalDateTime.of(2026, 3, 16, 0, 37, 12); // 월요일

    @Test
    void alignAndPrevious() {
        assertThat(Granularity.MINUTES.align(T)).isEqualTo(LocalDateTime.of(2026, 3, 16, 0, 30));
        assertThat(Granularity.MINUTES.previous(T)).isEqualTo(LocalDateTime.of(2026, 3, 16, 0, 20));
        assertThat(Granularity.HOURLY.previous(T)).isEqualTo(LocalDateTime.of(2026, 3, 15, 23, 0));
        assertThat(Granularity.DAILY.previous(T)).isEqualTo(LocalDateTime.of(2026, 3, 15, 0, 0));
        assertThat(Granularity.WEEKLY.previous(T)).isEqualTo(LocalDateTime.of(2026, 3, 9, 0, 0));
        assertThat(Granularity.WEEKLY.end(LocalDateTime.of(2026, 3, 9, 0, 0))).isEqualTo(LocalDateTime.of(2026, 3, 16, 0, 0));
    }

    @Test
    void dueGranularitiesMatchLegacyScheduler() {
        assertThat(due(LocalDateTime.of(2026, 3, 17, 13, 20))).containsExactly(Granularity.MINUTES);
        assertThat(due(LocalDateTime.of(2026, 3, 17, 13, 0))).containsExactly(Granularity.MINUTES, Granularity.HOURLY);
        assertThat(due(LocalDateTime.of(2026, 3, 17, 0, 10))).containsExactly(Granularity.MINUTES, Granularity.DAILY);
        assertThat(due(LocalDateTime.of(2026, 3, 16, 0, 30))).containsExactly(Granularity.MINUTES, Granularity.WEEKLY);
        assertThat(due(LocalDateTime.of(2026, 3, 17, 0, 30))).containsExactly(Granularity.MINUTES);
    }

    @Test
    void sqlTargetsMatchingTables() {
        assertThat(AggregationSql.delete(Granularity.WEEKLY, AggregationTarget.PAGE_STATS))
                .isEqualTo("DELETE FROM weekly_page_stats WHERE date = CAST(:bucket AS date)");
        // events 원천: 세그먼트 4개, 사용자 분포는 연령대/기기 2개씩
        assertThat(AggregationSql.inserts(Granularity.MINUTES, AggregationTarget.USER_DISTRIBUTION)).hasSize(8);
        assertThat(AggregationSql.inserts(Granularity.DAILY, AggregationTarget.CLICK_SUMMARY)).hasSize(4);
        assertThat(AggregationSql.inserts(Granularity.DAILY, AggregationTarget.METRICS).getFirst().sql())
                .contains("FROM hourly_metrics");
        assertThat(AggregationSql.inserts(Granularity.WEEKLY, AggregationTarget.TOP_ELEMENTS).getFirst().sql())
                .contains("FROM daily_top_elements").contains("date >= :startDate");
    }

    @Test
    void parsesLegacyArgumentFormats() {
        assertThat(AggregationCommand.parseTime("2025-07-12T14:30")).isEqualTo(LocalDateTime.of(2025, 7, 12, 14, 30));
        assertThat(AggregationCommand.parseTime("2025-07-12T14")).isEqualTo(LocalDateTime.of(2025, 7, 12, 14, 0));
        assertThat(AggregationCommand.parseTime("2025-07-12")).isEqualTo(LocalDateTime.of(2025, 7, 12, 0, 0));
        assertThatThrownBy(() -> AggregationCommand.parseTime("2025/07/12")).isInstanceOf(IllegalArgumentException.class);
    }

    private static List<Granularity> due(LocalDateTime tick) {
        return Arrays.stream(Granularity.values()).filter(g -> g.isDueAt(tick)).toList();
    }
}
