package com.klicklab.auth;

/** JWT 에서 복원한 로그인 사용자 (기존 req.user 와 동일한 필드) */
public record AuthUser(String userId, String email, String sdkKey) {
}
