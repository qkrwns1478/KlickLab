package com.klicklab.aggregation;

import com.klicklab.common.AppClock;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.stream.Stream;

/**
 * 명령행에서 집계를 한 번 실행하고 종료한다 (기존 node insert*.js / node test.js).
 *
 * <pre>
 * --aggregate=minutes [--at=2025-07-12T14:30]
 * --aggregate=hourly  [--at=2025-07-12T14]
 * --aggregate=daily   [--at=2025-07-12]
 * --aggregate=weekly  [--at=2025-07-07]          (해당 날짜부터 7일)
 * --aggregate=backfill [--from=2025-07-11] [--to=2025-07-12]
 * </pre>
 * {@code --at} 을 생략하면 직전 구간, {@code --from}/{@code --to} 를 생략하면 어제 하루를 집계한다.
 */
@Component
public class AggregationCommand implements ApplicationRunner {

    static final String OPTION = "aggregate";

    private final AggregationJobLauncher launcher;
    private final AppClock clock;

    public AggregationCommand(AggregationJobLauncher launcher, AppClock clock) {
        this.launcher = launcher;
        this.clock = clock;
    }

    public static boolean isRequested(String[] args) {
        return Arrays.stream(args).anyMatch(a -> a.startsWith("--" + OPTION + "="));
    }

    /** 웹 서버와 스케줄러 없이 앱을 띄워 집계만 실행하고 종료 코드를 돌려준다 */
    public static int execute(Class<?> source, String[] args) {
        SpringApplication app = new SpringApplication(source);
        app.setWebApplicationType(WebApplicationType.NONE);
        String[] withOverrides = Stream.concat(Arrays.stream(args), Stream.of(
                        "--klicklab.rollup.enabled=false",
                        "--klicklab.aggregation.enabled=false"))
                .toArray(String[]::new);
        try (ConfigurableApplicationContext context = app.run(withOverrides)) {
            return SpringApplication.exit(context);
        } catch (Exception e) {
            return 1;
        }
    }

    @Override
    public void run(ApplicationArguments args) {
        String command = value(args, OPTION);
        if (command == null) {
            return;
        }
        LocalDate yesterday = clock.today().minusDays(1);
        switch (command.toLowerCase(Locale.ROOT)) {
            case "backfill" -> {
                LocalDate from = date(args, "from", yesterday);
                LocalDate to = date(args, "to", from.isAfter(yesterday) ? from : yesterday);
                launcher.backfill(from, to);
            }
            case "minutes", "hourly", "daily", "weekly" -> {
                Granularity g = Granularity.valueOf(command.toUpperCase(Locale.ROOT));
                String at = value(args, "at");
                if (at == null) {
                    launcher.runPrevious(g);
                } else {
                    launcher.run(g, parseTime(at));
                }
            }
            default -> throw new IllegalArgumentException(
                    "--aggregate 값은 minutes, hourly, daily, weekly, backfill 중 하나여야 합니다: " + command);
        }
    }

    /** YYYY-MM-DD, YYYY-MM-DDTHH, YYYY-MM-DDTHH:mm */
    static LocalDateTime parseTime(String value) {
        try {
            if (value.matches("\\d{4}-\\d{2}-\\d{2}")) {
                return LocalDate.parse(value).atStartOfDay();
            }
            if (value.matches("\\d{4}-\\d{2}-\\d{2}T\\d{2}")) {
                return LocalDateTime.parse(value + ":00");
            }
            return LocalDateTime.parse(value);
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("날짜 형식 오류 (YYYY-MM-DD, YYYY-MM-DDTHH, YYYY-MM-DDTHH:mm): " + value, e);
        }
    }

    private static LocalDate date(ApplicationArguments args, String name, LocalDate defaultValue) {
        String value = value(args, name);
        return value == null ? defaultValue : parseTime(value).toLocalDate();
    }

    private static String value(ApplicationArguments args, String name) {
        List<String> values = args.getOptionValues(name);
        return values == null || values.isEmpty() ? null : values.getFirst();
    }
}
