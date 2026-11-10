package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 기존 index.js 통합 스케줄러.
 * 매 10분: minutes / 정각: + hourly / 매일 00:10: + daily / 매주 월요일 00:30: + weekly.
 * 상위 집계가 하위 집계를 원천으로 쓰므로 순서대로 실행하고, 실패하면 이후 단위는 건너뛴다.
 */
@Component
@ConditionalOnProperty(prefix = "klicklab.aggregation", name = "enabled", havingValue = "true", matchIfMissing = true)
public class AggregationScheduler {

    private static final Logger log = LoggerFactory.getLogger(AggregationScheduler.class);

    private final AggregationJobLauncher launcher;
    private final AppClock clock;

    public AggregationScheduler(AggregationJobLauncher launcher, AppClock clock) {
        this.launcher = launcher;
        this.clock = clock;
    }

    @Scheduled(cron = "0 */10 * * * *", zone = "${klicklab.timezone:Asia/Seoul}")
    public void runDue() {
        LocalDateTime tick = Granularity.MINUTES.align(clock.now().toLocalDateTime());
        for (Granularity g : Granularity.values()) {
            if (!g.isDueAt(tick)) {
                continue;
            }
            try {
                launcher.run(g, g.previous(tick));
            } catch (Exception e) {
                log.error("Scheduled aggregation failed at {}", tick, e);
                return;
            }
        }
    }
}
