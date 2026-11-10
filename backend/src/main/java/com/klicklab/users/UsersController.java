package com.klicklab.users;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.AppClock;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/users")
public class UsersController {

    private final Db db;
    private final AppClock clock;

    public UsersController(Db db, AppClock clock) {
        this.db = db;
        this.clock = clock;
    }

    /** 사용자 세그먼트 분석 (도시/연령/성별/기기 x 시간별) */
    @GetMapping("/realtime-analytics")
    public Map<String, Object> realtimeAnalytics(@AuthenticationPrincipal AuthUser user,
                                                 @RequestParam(required = false) String startDate,
                                                 @RequestParam(required = false) String endDate) {
        DateRange range = DateRange.orDefault(startDate, endDate, clock, 7);
        LocalDate today = clock.today();
        List<Map<String, Object>> rows = db.list("""
                SELECT summary_date, summary_hour, city, age_group, gender, device_type, device_os,
                    sum(users) AS users,
                    sum(sessions) AS sessions,
                    sum(session_duration_sum) AS session_duration_sum
                FROM agg_user_session_hourly
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY summary_date, summary_hour, city, age_group, gender, device_type, device_os
                ORDER BY summary_date, summary_hour
                """, range.params(user.sdkKey()));

        String todayStr = today.toString();
        long todayRecords = rows.stream().filter(r -> todayStr.equals(r.get("summary_date"))).count();
        ZonedDateTime now = clock.now();

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("isOnlyToday", range.start().equals(today) && range.end().equals(today));
        meta.put("includesOnlyToday", range.contains(today));
        meta.put("pastRecords", rows.size() - todayRecords);
        meta.put("todayRecords", todayRecords);
        meta.put("currentTime", now.getHour() + ":" + now.getMinute());

        return Map.of("data", rows, "meta", meta);
    }
}
