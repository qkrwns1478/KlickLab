package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.batch.core.BatchStatus;
import org.springframework.batch.core.job.Job;
import org.springframework.batch.core.job.JobExecution;
import org.springframework.batch.core.job.parameters.JobParameters;
import org.springframework.batch.core.job.parameters.JobParametersBuilder;
import org.springframework.batch.core.launch.JobOperator;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.EnumMap;
import java.util.Map;

/** 집계 Job 실행 (스케줄러, 명령행 실행, 테스트에서 공통 사용) */
@Service
public class AggregationJobLauncher {

    static final String BUCKET_START = "bucketStart";
    private static final String REQUESTED_AT = "requestedAt";

    private static final Logger log = LoggerFactory.getLogger(AggregationJobLauncher.class);

    private final JobOperator jobOperator;
    private final AppClock clock;
    private final Map<Granularity, Job> jobs = new EnumMap<>(Granularity.class);

    public AggregationJobLauncher(JobOperator jobOperator, AppClock clock, Map<String, Job> jobsByName) {
        this.jobOperator = jobOperator;
        this.clock = clock;
        for (Granularity g : Granularity.values()) {
            Job job = jobsByName.get(AggregationJobConfig.jobName(g));
            if (job == null) {
                throw new IllegalStateException("집계 Job 이 없습니다: " + AggregationJobConfig.jobName(g));
            }
            jobs.put(g, job);
        }
    }

    /**
     * bucketStart 가 속한 구간 하나를 집계한다. 같은 구간을 다시 실행하면 기존 집계를 덮어쓴다.
     *
     * @throws AggregationFailedException Job 이 COMPLETED 로 끝나지 않은 경우
     */
    public JobExecution run(Granularity g, LocalDateTime bucketStart) {
        LocalDateTime start = g.align(bucketStart);
        JobParameters params = new JobParametersBuilder()
                .addLocalDateTime(BUCKET_START, start)
                // 같은 구간의 재실행을 허용하기 위해 실행마다 새 JobInstance 로 만든다
                .addLocalDateTime(REQUESTED_AT, LocalDateTime.now())
                .toJobParameters();
        JobExecution execution;
        try {
            execution = jobOperator.start(jobs.get(g), params);
        } catch (Exception e) {
            throw new AggregationFailedException(g, start, e);
        }
        if (execution.getStatus() != BatchStatus.COMPLETED) {
            Throwable cause = execution.getAllFailureExceptions().stream().findFirst().orElse(null);
            throw new AggregationFailedException(g, start, cause);
        }
        log.info("{} 집계 완료: {} ~ {}", g.prefix(), start, g.end(start));
        return execution;
    }

    /** now 기준 직전 구간을 집계한다 (기존 워커를 인자 없이 실행한 경우) */
    public JobExecution runPrevious(Granularity g) {
        return run(g, g.previous(clock.now().toLocalDateTime()));
    }

    /**
     * from ~ to (양끝 포함) 기간을 다시 집계한다 (기존 test.js).
     * 날짜마다 10분 → 1시간 → 1일 순서로, 이후 from 부터 7일씩 끊어 주간을 집계한다.
     * 아직 끝나지 않은 구간은 건너뛴다.
     */
    public void backfill(LocalDate from, LocalDate to) {
        if (to.isBefore(from)) {
            throw new IllegalArgumentException("종료 날짜가 시작 날짜보다 앞섭니다: " + from + " ~ " + to);
        }
        LocalDateTime now = clock.now().toLocalDateTime();
        log.info("집계 백필 시작: {} ~ {}", from, to);
        for (LocalDate day = from; !day.isAfter(to); day = day.plusDays(1)) {
            LocalDateTime dayStart = day.atStartOfDay();
            runCompleted(Granularity.MINUTES, dayStart, Granularity.DAILY.end(dayStart), now);
            runCompleted(Granularity.HOURLY, dayStart, Granularity.DAILY.end(dayStart), now);
            runCompleted(Granularity.DAILY, dayStart, Granularity.DAILY.end(dayStart), now);
        }
        for (LocalDate week = from; !week.plusDays(6).isAfter(to); week = week.plusDays(7)) {
            runCompleted(Granularity.WEEKLY, week.atStartOfDay(), Granularity.WEEKLY.end(week.atStartOfDay()), now);
        }
        log.info("집계 백필 완료: {} ~ {}", from, to);
    }

    private void runCompleted(Granularity g, LocalDateTime from, LocalDateTime until, LocalDateTime now) {
        for (LocalDateTime start = from; start.isBefore(until); start = g.end(start)) {
            if (g.end(start).isAfter(now)) {
                return;
            }
            run(g, start);
        }
    }

    public static class AggregationFailedException extends RuntimeException {
        AggregationFailedException(Granularity g, LocalDateTime start, Throwable cause) {
            super(g.prefix() + " 집계 실패: " + start, cause);
        }
    }
}
