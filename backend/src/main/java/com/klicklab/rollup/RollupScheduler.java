package com.klicklab.rollup;

import com.klicklab.common.AppClock;
import com.klicklab.config.KlickLabProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.task.TaskExecutor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 주기적으로 오늘(필요 시 어제) 집계를 갱신하고, 기동 시 누락된 날짜를 채운다.
 */
@Component
@ConditionalOnProperty(prefix = "klicklab.rollup", name = "enabled", havingValue = "true", matchIfMissing = true)
public class RollupScheduler {

    private static final Logger log = LoggerFactory.getLogger(RollupScheduler.class);

    private final RollupService rollupService;
    private final AppClock clock;
    private final KlickLabProperties.Rollup props;
    private final TaskExecutor taskExecutor;

    public RollupScheduler(RollupService rollupService, AppClock clock, KlickLabProperties properties,
                           @Qualifier("applicationTaskExecutor") TaskExecutor taskExecutor) {
        this.rollupService = rollupService;
        this.clock = clock;
        this.props = properties.rollup();
        this.taskExecutor = taskExecutor;
    }

    @Scheduled(cron = "${klicklab.rollup.cron:0 */5 * * * *}", zone = "${klicklab.timezone:Asia/Seoul}")
    public void refreshRecent() {
        LocalDate today = clock.today();
        try {
            // 자정 직후에는 늦게 도착한 이벤트를 위해 어제도 다시 계산
            if (clock.now().toOffsetDateTime().isBefore(clock.startOf(today).plus(props.lateArrivalGrace()))) {
                rollupService.refresh(today.minusDays(1));
            }
            rollupService.refresh(today);
        } catch (Exception e) {
            log.error("Scheduled rollup failed", e);
        }
    }

    @EventListener(ApplicationReadyEvent.class)
    public void backfillOnStartup() {
        int days = props.backfillDaysOnStartup();
        if (days <= 0) {
            return;
        }
        taskExecutor.execute(() -> {
            LocalDate today = clock.today();
            Set<LocalDate> targets = new LinkedHashSet<>(rollupService.missingDays(today.minusDays(days), today));
            targets.add(today.minusDays(1));
            targets.add(today);
            log.info("Rollup backfill on startup: {} day(s)", targets.size());
            for (LocalDate day : targets) {
                try {
                    rollupService.refresh(day);
                } catch (Exception e) {
                    log.error("Rollup backfill failed for {}", day, e);
                }
            }
        });
    }
}
