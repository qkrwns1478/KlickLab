package com.klicklab.auth;

import com.klicklab.config.KlickLabProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Optional;

/**
 * HS256 JWT 발급/검증. 클레임(userId, email, sdk_key)은 기존 Node.js(jsonwebtoken) 서버와 동일하다.
 */
@Service
public class JwtService {

    private static final int MIN_SECRET_BYTES = 32;

    private final SecretKey accessKey;
    private final SecretKey refreshKey;
    private final KlickLabProperties.Jwt props;

    public JwtService(KlickLabProperties properties) {
        this.props = properties.jwt();
        this.accessKey = toKey("JWT_SECRET", props.secret());
        this.refreshKey = toKey("JWT_REFRESH_SECRET", props.refreshSecret());
    }

    public String createAccessToken(AuthUser user) {
        return sign(user, accessKey, props.accessTtl());
    }

    /** refresh 로 재발급하는 access token (기존 동작: 150분) */
    public String createRefreshedAccessToken(AuthUser user) {
        return sign(user, accessKey, props.refreshedAccessTtl());
    }

    public String createRefreshToken(AuthUser user) {
        return sign(user, refreshKey, props.refreshTtl());
    }

    public Duration refreshTtl() {
        return props.refreshTtl();
    }

    public Optional<AuthUser> parseAccessToken(String token) {
        return parse(token, accessKey);
    }

    public Optional<AuthUser> parseRefreshToken(String token) {
        return parse(token, refreshKey);
    }

    private String sign(AuthUser user, SecretKey key, Duration ttl) {
        Instant now = Instant.now();
        return Jwts.builder()
                .claim("userId", user.userId())
                .claim("email", user.email())
                .claim("sdk_key", user.sdkKey())
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(ttl)))
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    private Optional<AuthUser> parse(String token, SecretKey key) {
        try {
            Claims claims = Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
            Object userId = claims.get("userId");
            return Optional.of(new AuthUser(
                    userId == null ? null : userId.toString(),
                    claims.get("email", String.class),
                    claims.get("sdk_key", String.class)));
        } catch (JwtException | IllegalArgumentException e) {
            return Optional.empty();
        }
    }

    private static SecretKey toKey(String name, String secret) {
        if (secret == null || secret.isBlank()) {
            throw new IllegalStateException(name + " 환경변수가 설정되지 않았습니다.");
        }
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(name + " 는 HS256 서명을 위해 최소 " + MIN_SECRET_BYTES + "바이트 이상이어야 합니다.");
        }
        return Keys.hmacShaKeyFor(bytes);
    }
}
