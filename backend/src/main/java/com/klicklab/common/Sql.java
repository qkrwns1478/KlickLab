package com.klicklab.common;

/** 여러 쿼리에서 공유하는 SQL 조각 */
public final class Sql {

    private Sql() {
    }

    /** 방문자 식별자 (RollupService 의 client_id 정의와 동일) */
    public static final String CLIENT = "COALESCE(NULLIF(client_id, ''), NULLIF(user_id, ''), session_id)";

    /** 클릭 이벤트로 취급하는 event_name 목록 */
    public static final String CLICK_EVENTS = "('auto_click', 'user_click', 'click')";
}
