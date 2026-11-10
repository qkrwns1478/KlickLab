package com.klicklab.funnel;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.DateRange;
import com.klicklab.common.Db;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/** 퍼널 Sankey: 시작 페이지 / 다음 단계 Top N */
@RestController
@RequestMapping("/api/funnel")
public class FunnelController {

    public record MultiStepRequest(List<String> steps, String from, String to, Integer limit) {
    }

    private final Db db;

    public FunnelController(Db db) {
        this.db = db;
    }

    @GetMapping("/path/next")
    public ResponseEntity<?> next(@AuthenticationPrincipal AuthUser user,
                                  @RequestParam(required = false) String page,
                                  @RequestParam(required = false) String from,
                                  @RequestParam(required = false) String to,
                                  @RequestParam(defaultValue = "5") int limit) {
        if (isBlank(page) || isBlank(from) || isBlank(to)) {
            return ResponseEntity.badRequest().body(Map.of("error", "page, from, to are required"));
        }
        return ResponseEntity.ok(nextSteps(user.sdkKey(), page, DateRange.required(from, to), limit));
    }

    @GetMapping("/start-pages")
    public List<Map<String, Object>> startPages(@AuthenticationPrincipal AuthUser user,
                                                @RequestParam String from,
                                                @RequestParam String to,
                                                @RequestParam(defaultValue = "50") int limit) {
        return db.list("""
                SELECT page_path, sum(sessions) AS sessions
                FROM agg_first_pages_daily
                WHERE sdk_key = :sdkKey AND summary_date BETWEEN :start AND :end
                GROUP BY page_path
                ORDER BY sessions DESC
                LIMIT :limit
                """, DateRange.required(from, to).params(user.sdkKey()).addValue("limit", clamp(limit)));
    }

    /** 다단계 경로: 마지막으로 선택된 페이지의 다음 단계 */
    @PostMapping("/path/multi-step")
    public ResponseEntity<?> multiStep(@AuthenticationPrincipal AuthUser user, @RequestBody MultiStepRequest body) {
        if (body.steps() == null || body.steps().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "steps array is required"));
        }
        String lastStep = body.steps().getLast();
        int limit = body.limit() == null ? 5 : body.limit();
        return ResponseEntity.ok(nextSteps(user.sdkKey(), lastStep, DateRange.required(body.from(), body.to()), limit));
    }

    private List<Map<String, Object>> nextSteps(String sdkKey, String page, DateRange range, int limit) {
        return db.list("""
                SELECT target, sum(sessions) AS sessions
                FROM agg_funnel_links_daily
                WHERE sdk_key = :sdkKey AND source = :page AND summary_date BETWEEN :start AND :end
                GROUP BY target
                ORDER BY sessions DESC
                LIMIT :limit
                """, range.params(sdkKey).addValue("page", page).addValue("limit", clamp(limit)));
    }

    private static int clamp(int limit) {
        return Math.max(1, Math.min(limit, 1000));
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
