package com.klicklab.traffic;

import java.time.LocalDate;

/** 패키지 전용 메서드를 테스트에서 호출하기 위한 접근자 */
public final class TrafficServiceTestAccess {

    private TrafficServiceTestAccess() {
    }

    public static String weekLabel(LocalDate date) {
        return TrafficService.weekLabel(date);
    }
}
