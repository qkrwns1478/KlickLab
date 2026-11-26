package com.klicklab;

import com.klicklab.auth.AuthUser;
import com.klicklab.auth.JwtService;
import com.klicklab.common.JsonText;
import com.klicklab.config.KlickLabProperties;
import com.klicklab.traffic.TrafficServiceTestAccess;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Date;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class UnitTests {

    static final String SECRET = "unit-test-access-secret-0123456789abcdef";
    static final String REFRESH = "unit-test-refresh-secret-0123456789abcdef";

    static KlickLabProperties props(String secret) {
        return new KlickLabProperties(ZoneId.of("Asia/Seoul"),
                new KlickLabProperties.Jwt(secret, REFRESH, Duration.ofMinutes(15), Duration.ofMinutes(150), Duration.ofDays(7)),
                new KlickLabProperties.Cors(List.of()),
                new KlickLabProperties.Auth(false),
                new KlickLabProperties.Rollup(false, Duration.ofHours(1), 0));
    }

    @Test
    void jwtRoundTrip() {
        JwtService jwt = new JwtService(props(SECRET));
        AuthUser user = new AuthUser("id-1", "a@b.com", "sdk-1");
        assertThat(jwt.parseAccessToken(jwt.createAccessToken(user))).contains(user);
        assertThat(jwt.parseRefreshToken(jwt.createRefreshToken(user))).contains(user);
        // access 키로 서명된 토큰은 refresh 검증에 실패해야 함
        assertThat(jwt.parseRefreshToken(jwt.createAccessToken(user))).isEmpty();
    }

    @Test
    void acceptsTokensIssuedByLegacyNodeServer() {
        // jsonwebtoken(Node) 이 발급한 것과 같은 형태: HS256 + userId/email/sdk_key 클레임
        String legacy = Jwts.builder()
                .claim("userId", "42").claim("email", "a@b.com").claim("sdk_key", "sdk-1")
                .expiration(new Date(System.currentTimeMillis() + 60_000))
                .signWith(Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256)
                .compact();
        assertThat(new JwtService(props(SECRET)).parseAccessToken(legacy))
                .contains(new AuthUser("42", "a@b.com", "sdk-1"));
    }

    @Test
    void rejectsShortSecret() {
        assertThatThrownBy(() -> new JwtService(props("short"))).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void weekLabelMatchesLegacyFormula() {
        // 2026-03-01 은 일요일 → 3월 1일은 1주차, 3월 2일(월)부터 2주차
        assertThat(TrafficServiceTestAccess.weekLabel(LocalDate.of(2026, 3, 1))).isEqualTo("03월 1주차");
        assertThat(TrafficServiceTestAccess.weekLabel(LocalDate.of(2026, 3, 2))).isEqualTo("03월 2주차");
        assertThat(TrafficServiceTestAccess.weekLabel(LocalDate.of(2026, 3, 15))).isEqualTo("03월 3주차");
    }

    @Test
    void jsonTextQuotes() {
        assertThat(JsonText.quote("a\"b\\c")).isEqualTo("\"a\\\"b\\\\c\"");
    }
}
