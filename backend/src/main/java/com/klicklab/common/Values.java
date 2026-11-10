package com.klicklab.common;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Map 기반 조회 결과에서 숫자/문자열을 꺼낼 때 사용하는 변환 유틸 */
public final class Values {

    private Values() {
    }

    public static long toLong(Object value) {
        return switch (value) {
            case null -> 0L;
            case Number n -> n.longValue();
            case String s -> {
                try {
                    yield new BigDecimal(s.trim()).longValue();
                } catch (NumberFormatException e) {
                    yield 0L;
                }
            }
            default -> 0L;
        };
    }

    public static double toDouble(Object value) {
        return switch (value) {
            case null -> 0d;
            case Number n -> n.doubleValue();
            case String s -> {
                try {
                    yield Double.parseDouble(s.trim());
                } catch (NumberFormatException e) {
                    yield 0d;
                }
            }
            default -> 0d;
        };
    }

    public static String str(Object value) {
        return value == null ? "" : value.toString();
    }

    /** JS 의 Math.round 와 같은 반올림 (half-up) */
    public static long round(double value) {
        return (long) Math.floor(value + 0.5);
    }

    /** 소수점 scale 자리 반올림 */
    public static double round(double value, int scale) {
        if (Double.isNaN(value) || Double.isInfinite(value)) {
            return 0d;
        }
        return BigDecimal.valueOf(value).setScale(scale, RoundingMode.HALF_UP).doubleValue();
    }
}
