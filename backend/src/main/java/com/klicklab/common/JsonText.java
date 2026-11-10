package com.klicklab.common;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

/** 문자열 하나를 JSON 문자열 리터럴로 응답 (Express 의 res.json("...") 호환) */
public final class JsonText {

    private JsonText() {
    }

    public static ResponseEntity<String> ok(String value) {
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(quote(value));
    }

    public static String quote(String value) {
        if (value == null) {
            return "null";
        }
        StringBuilder sb = new StringBuilder(value.length() + 2).append('"');
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.append('"').toString();
    }
}
