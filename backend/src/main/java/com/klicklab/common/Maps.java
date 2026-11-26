package com.klicklab.common;

import java.util.LinkedHashMap;
import java.util.Map;

public final class Maps {

    private Maps() {
    }

    /** 순서를 유지하는 Map 생성 (key, value, key, value ...), null 값 허용 */
    public static Map<String, Object> obj(Object... keyValues) {
        if (keyValues.length % 2 != 0) {
            throw new IllegalArgumentException("obj must be key/value pairs");
        }
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < keyValues.length; i += 2) {
            m.put((String) keyValues[i], keyValues[i + 1]);
        }
        return m;
    }
}
