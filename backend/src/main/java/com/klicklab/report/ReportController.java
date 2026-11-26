package com.klicklab.report;

import com.klicklab.auth.AuthUser;
import com.klicklab.common.DateRange;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.HtmlUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static com.klicklab.common.Maps.obj;

@RestController
@RequestMapping("/api/report")
public class ReportController {

    private static final MediaType TEXT_CSV = MediaType.parseMediaType("text/csv; charset=utf-8");
    private static final MediaType TEXT_PLAIN = MediaType.parseMediaType("text/plain; charset=utf-8");
    private static final MediaType TEXT_MARKDOWN = MediaType.parseMediaType("text/markdown; charset=utf-8");
    private static final MediaType TEXT_HTML = MediaType.parseMediaType("text/html; charset=utf-8");

    private final KpiReportService kpiReportService;

    public ReportController(KpiReportService kpiReportService) {
        this.kpiReportService = kpiReportService;
    }

    @GetMapping("/kpi-report")
    public Map<String, Object> kpiReport(@AuthenticationPrincipal AuthUser user,
                                         @RequestParam(required = false) String startDate,
                                         @RequestParam(required = false) String endDate) {
        Map<String, Object> response = new LinkedHashMap<>();
        for (KpiReportService.Section s : sections(user, startDate, endDate)) {
            response.put(s.key(), obj("category", s.category(), "data", s.data()));
        }
        return response;
    }

    /** 클라이언트가 보낸 리포트 데이터를 CSV 로 변환 (인증 불필요, 기존과 동일) */
    @PostMapping("/kpi-report/csv")
    public ResponseEntity<String> csv(@RequestBody(required = false) Map<String, Object> reportData) {
        if (reportData == null) {
            return ResponseEntity.badRequest().contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"Missing or invalid report data\"}");
        }
        StringBuilder out = new StringBuilder("﻿");
        for (Object value : reportData.values()) {
            if (!(value instanceof Map<?, ?> section) || !(section.get("data") instanceof List<?> data) || data.isEmpty()
                    || !(data.getFirst() instanceof Map<?, ?> first)) {
                continue;
            }
            out.append("## ").append(section.get("category")).append('\n');
            List<String> headers = first.keySet().stream().map(String::valueOf).toList();
            out.append(headers.stream().map(ReportController::csvField).collect(Collectors.joining(","))).append('\n');
            for (Object item : data) {
                if (!(item instanceof Map<?, ?> row)) {
                    continue;
                }
                List<String> fields = new ArrayList<>(headers.size());
                for (String h : headers) {
                    Object v = row.get(h);
                    String text = v == null ? "" : String.valueOf(v);
                    // date 는 엑셀 자동 변환 방지
                    fields.add(csvField("date".equals(h) && v != null ? "=\"" + text + "\"" : text));
                }
                out.append(String.join(",", fields)).append('\n');
            }
            out.append("\n\n");
        }
        String fileName = "kpi-report-export-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss")) + ".csv";
        return download(TEXT_CSV, fileName, out.toString());
    }

    @GetMapping("/kpi-report/txt")
    public ResponseEntity<String> txt(@AuthenticationPrincipal AuthUser user,
                                      @RequestParam(required = false) String startDate,
                                      @RequestParam(required = false) String endDate) {
        StringBuilder out = new StringBuilder();
        for (KpiReportService.Section s : sections(user, startDate, endDate)) {
            if (s.data().isEmpty()) {
                continue;
            }
            List<String> headers = headers(s);
            out.append("## ").append(s.category()).append('\n');
            out.append(String.join("\t", headers)).append('\n');
            for (Map<String, Object> row : s.data()) {
                out.append(headers.stream().map(h -> text(row.get(h))).collect(Collectors.joining("\t"))).append('\n');
            }
            out.append('\n');
        }
        return download(TEXT_PLAIN, "kpi-report-" + startDate + "_to_" + endDate + ".txt", out.toString());
    }

    @GetMapping("/kpi-report/md")
    public ResponseEntity<String> markdown(@AuthenticationPrincipal AuthUser user,
                                           @RequestParam(required = false) String startDate,
                                           @RequestParam(required = false) String endDate) {
        List<KpiReportService.Section> sections = sections(user, startDate, endDate);
        StringBuilder out = new StringBuilder("# KPI 리포트 (" + startDate + " ~ " + endDate + ")\n\n");
        for (KpiReportService.Section s : sections) {
            if (s.data().isEmpty()) {
                continue;
            }
            List<String> headers = headers(s);
            out.append("## ").append(s.category()).append("\n\n");
            out.append("| ").append(String.join(" | ", headers)).append(" |\n");
            out.append("| ").append(headers.stream().map(h -> "---").collect(Collectors.joining(" | "))).append(" |\n");
            for (Map<String, Object> row : s.data()) {
                out.append("| ").append(headers.stream().map(h -> text(row.get(h)).replace("|", "\\|"))
                        .collect(Collectors.joining(" | "))).append(" |\n");
            }
            out.append('\n');
        }
        return download(TEXT_MARKDOWN, "kpi-report-" + startDate + "_to_" + endDate + ".md", out.toString());
    }

    @GetMapping("/kpi-report/html")
    public ResponseEntity<String> html(@AuthenticationPrincipal AuthUser user,
                                       @RequestParam(required = false) String startDate,
                                       @RequestParam(required = false) String endDate) {
        List<KpiReportService.Section> sections = sections(user, startDate, endDate);
        StringBuilder html = new StringBuilder("""
                <!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><title>KPI 리포트</title>
                  <style>
                    body { font-family: sans-serif; padding: 20px; }
                    h1 { font-size: 22px; margin-top: 40px; }
                    table { border-collapse: collapse; width: 100%; margin-top: 10px; margin-bottom: 30px; }
                    th, td { border: 1px solid #ccc; padding: 8px; text-align: center; font-size: 13px; }
                    th { background-color: #f0f0f0; }
                  </style>
                </head><body>""");
        html.append("<h1>KPI 리포트 (").append(esc(startDate)).append(" ~ ").append(esc(endDate)).append(")</h1>");
        for (KpiReportService.Section s : sections) {
            if (s.data().isEmpty()) {
                continue;
            }
            List<String> headers = headers(s);
            html.append("<h2>").append(esc(s.category())).append("</h2><table><thead><tr>");
            headers.forEach(h -> html.append("<th>").append(esc(h)).append("</th>"));
            html.append("</tr></thead><tbody>");
            for (Map<String, Object> row : s.data()) {
                html.append("<tr>");
                headers.forEach(h -> html.append("<td>").append(esc(text(row.get(h)))).append("</td>"));
                html.append("</tr>");
            }
            html.append("</tbody></table>");
        }
        html.append("</body></html>");
        return download(TEXT_HTML, "kpi-report-" + startDate + "_to_" + endDate + ".html", html.toString());
    }

    private List<KpiReportService.Section> sections(AuthUser user, String startDate, String endDate) {
        return kpiReportService.build(user.sdkKey(), DateRange.required(startDate, endDate));
    }

    private static List<String> headers(KpiReportService.Section s) {
        return new ArrayList<>(s.data().getFirst().keySet());
    }

    private static ResponseEntity<String> download(MediaType type, String fileName, String body) {
        return ResponseEntity.ok()
                .contentType(type)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + fileName + "\"")
                .body(body);
    }

    /** fast-csv 와 동일한 규칙: 구분자/따옴표/개행이 있으면 따옴표로 감싸고 따옴표는 두 번 */
    static String csvField(String value) {
        if (value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r")) {
            return "\"" + value.replace("\"", "\"\"") + "\"";
        }
        return value;
    }

    private static String text(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static String esc(String s) {
        return HtmlUtils.htmlEscape(s == null ? "" : s);
    }
}
