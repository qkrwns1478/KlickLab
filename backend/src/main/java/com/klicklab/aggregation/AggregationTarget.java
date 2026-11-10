package com.klicklab.aggregation;

/** 집계 대상 테이블 종류 (테이블명 = {단위}_{suffix}) */
public enum AggregationTarget {

    METRICS("metrics"),
    CLICK_SUMMARY("click_summary"),
    TOP_ELEMENTS("top_elements"),
    USER_DISTRIBUTION("user_distribution"),
    PAGE_STATS("page_stats");

    private final String suffix;

    AggregationTarget(String suffix) {
        this.suffix = suffix;
    }

    public String suffix() {
        return suffix;
    }

    /**
     * events 에서 바로 집계하는지 여부. 그 외에는 바로 아래 단위 테이블을 합산한다.
     * (기존 워커와 동일: 일간 세그먼트 통계는 일 단위 순 사용자 수를 위해 events 에서 다시 계산)
     */
    public boolean readsEvents(Granularity granularity) {
        return granularity == Granularity.MINUTES
                || (granularity == Granularity.DAILY && this != METRICS && this != PAGE_STATS);
    }
}
