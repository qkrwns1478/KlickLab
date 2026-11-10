package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.springframework.batch.core.job.Job;
import org.springframework.batch.core.job.builder.JobBuilder;
import org.springframework.batch.core.job.builder.SimpleJobBuilder;
import org.springframework.batch.core.repository.JobRepository;
import org.springframework.batch.core.step.Step;
import org.springframework.batch.core.step.builder.StepBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

/**
 * 집계 Job 정의. 단위(minutes/hourly/daily/weekly)마다 Job 하나, 집계 테이블마다 Step 하나.
 *
 * <pre>
 * minutesAggregationJob : events                 → minutes_*  (기존 insertMM / insertMU / insertMP)
 * hourlyAggregationJob  : minutes_*              → hourly_*   (기존 insertHM / insertHU / insertHP)
 * dailyAggregationJob   : hourly_* 또는 events   → daily_*    (기존 insertDM / insertDU / insertDP)
 * weeklyAggregationJob  : daily_*                → weekly_*   (기존 insertWM / insertWU / insertWP)
 * </pre>
 */
@Configuration
public class AggregationJobConfig {

    private final JobRepository jobRepository;
    private final PlatformTransactionManager transactionManager;
    private final NamedParameterJdbcTemplate jdbc;
    private final AppClock clock;

    public AggregationJobConfig(JobRepository jobRepository, PlatformTransactionManager transactionManager,
                                NamedParameterJdbcTemplate jdbc, AppClock clock) {
        this.jobRepository = jobRepository;
        this.transactionManager = transactionManager;
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Bean
    public Job minutesAggregationJob() {
        return aggregationJob(Granularity.MINUTES);
    }

    @Bean
    public Job hourlyAggregationJob() {
        return aggregationJob(Granularity.HOURLY);
    }

    @Bean
    public Job dailyAggregationJob() {
        return aggregationJob(Granularity.DAILY);
    }

    @Bean
    public Job weeklyAggregationJob() {
        return aggregationJob(Granularity.WEEKLY);
    }

    static String jobName(Granularity g) {
        return g.prefix() + "AggregationJob";
    }

    private Job aggregationJob(Granularity g) {
        AggregationTarget[] targets = AggregationTarget.values();
        SimpleJobBuilder builder = new JobBuilder(jobName(g), jobRepository).start(step(g, targets[0]));
        for (int i = 1; i < targets.length; i++) {
            builder = builder.next(step(g, targets[i]));
        }
        return builder.build();
    }

    private Step step(Granularity g, AggregationTarget target) {
        return new StepBuilder(g.table(target.suffix()), jobRepository)
                .tasklet(new AggregationTasklet(g, target, jdbc, clock), transactionManager)
                .build();
    }
}
