package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.batch.core.scope.context.ChunkContext;
import org.springframework.batch.core.step.StepContribution;
import org.springframework.batch.core.step.tasklet.Tasklet;
import org.springframework.batch.infrastructure.repeat.RepeatStatus;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;

/**
 * 한 구간의 집계 테이블 하나를 다시 계산한다 (DELETE 후 INSERT … SELECT).
 * Step 트랜잭션 안에서 실행되므로 실패하면 기존 행이 그대로 남고, 재실행해도 결과가 같다.
 */
class AggregationTasklet implements Tasklet {

    private static final Logger log = LoggerFactory.getLogger(AggregationTasklet.class);

    private final Granularity granularity;
    private final AggregationTarget target;
    private final NamedParameterJdbcTemplate jdbc;
    private final AppClock clock;

    AggregationTasklet(Granularity granularity, AggregationTarget target, NamedParameterJdbcTemplate jdbc, AppClock clock) {
        this.granularity = granularity;
        this.target = target;
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Override
    public RepeatStatus execute(StepContribution contribution, ChunkContext chunkContext) {
        LocalDateTime start = chunkContext.getStepContext().getStepExecution().getJobParameters()
                .getLocalDateTime(AggregationJobLauncher.BUCKET_START);
        LocalDateTime end = granularity.end(start);
        OffsetDateTime startAt = start.atZone(clock.zone()).toOffsetDateTime();
        OffsetDateTime endAt = end.atZone(clock.zone()).toOffsetDateTime();
        String table = granularity.table(target.suffix());

        MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("bucket", granularity.isDateBased() ? start.toLocalDate() : startAt)
                .addValue("start", startAt)
                .addValue("end", endAt)
                .addValue("startDate", start.toLocalDate())
                .addValue("endDate", end.toLocalDate())
                .addValue("table", table);

        // 같은 테이블을 동시에 다시 쓰는 실행(스케줄 + 수동 실행)을 직렬화
        jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtext(:table))", params);
        int deleted = jdbc.update(AggregationSql.delete(granularity, target), params);
        int inserted = 0;
        for (AggregationSql.Statement statement : AggregationSql.inserts(granularity, target)) {
            MapSqlParameterSource p = new MapSqlParameterSource(params.getValues()).addValues(statement.params());
            inserted += jdbc.update(statement.sql(), p);
        }
        contribution.incrementWriteCount(inserted);
        log.debug("{} [{} ~ {}): deleted {}, inserted {}", table, start, end, deleted, inserted);
        return RepeatStatus.FINISHED;
    }
}
