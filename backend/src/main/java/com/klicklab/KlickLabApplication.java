package com.klicklab;

import com.klicklab.aggregation.AggregationCommand;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
public class KlickLabApplication {

    public static void main(String[] args) {
        // --aggregate=... : 웹 서버 없이 집계 Job 만 실행하고 종료
        if (AggregationCommand.isRequested(args)) {
            System.exit(AggregationCommand.execute(KlickLabApplication.class, args));
        }
        SpringApplication.run(KlickLabApplication.class, args);
    }
}
