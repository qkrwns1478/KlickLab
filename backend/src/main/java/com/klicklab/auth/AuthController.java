package com.klicklab.auth;

import com.klicklab.config.KlickLabProperties;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final String REFRESH_COOKIE = "refreshToken";
    private static final Pattern EMAIL = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@.]{2,}$");
    private static final String LOGIN_FAILED = "이메일 또는 비밀번호가 잘못되었습니다.";

    public record Credentials(String email, String password) {
    }

    private final UserAccountRepository users;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final boolean autoApprove;

    public AuthController(UserAccountRepository users, PasswordEncoder passwordEncoder, JwtService jwtService,
                          KlickLabProperties properties) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.autoApprove = properties.auth().autoApprove();
    }

    @PostMapping("/login")
    public ResponseEntity<Map<String, Object>> login(@RequestBody Credentials body) {
        if (body.email() == null || body.password() == null) {
            return unauthorized(LOGIN_FAILED);
        }
        Optional<UserAccountRepository.UserAccount> found = users.findByEmail(body.email());
        if (found.isEmpty() || !passwordEncoder.matches(body.password(), found.get().passwordHash())) {
            return unauthorized(LOGIN_FAILED);
        }
        UserAccountRepository.UserAccount user = found.get();
        if (!user.approved()) {
            return unauthorized("관리자 승인 후 로그인이 가능합니다.");
        }

        AuthUser authUser = user.toAuthUser();
        ResponseCookie cookie = refreshCookie(jwtService.createRefreshToken(authUser), jwtService.refreshTtl());
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .body(Map.of("accessToken", jwtService.createAccessToken(authUser)));
    }

    @PostMapping("/refresh")
    public ResponseEntity<Map<String, Object>> refresh(
            @CookieValue(name = REFRESH_COOKIE, required = false) String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            return unauthorized("Refresh token 없음");
        }
        return jwtService.parseRefreshToken(refreshToken)
                .map(user -> ResponseEntity.ok(
                        Map.<String, Object>of("accessToken", jwtService.createRefreshedAccessToken(user))))
                .orElseGet(() -> unauthorized("Refresh token이 유효하지 않음"));
    }

    @PostMapping("/logout")
    public ResponseEntity<Map<String, Object>> logout() {
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, refreshCookie("", Duration.ZERO).toString())
                .body(Map.of("message", "로그아웃되었습니다."));
    }

    @PostMapping("/register")
    public ResponseEntity<Map<String, Object>> register(@RequestBody Credentials body) {
        if (body.email() == null || !EMAIL.matcher(body.email().trim()).matches()) {
            return ResponseEntity.badRequest().body(Map.of("message", "유효한 이메일 주소를 입력해주세요."));
        }
        if (body.password() == null || body.password().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("message", "비밀번호를 입력해주세요."));
        }
        String email = body.email().trim();
        if (users.findByEmail(email).isPresent()) {
            return conflict();
        }
        try {
            String id = users.create(email, passwordEncoder.encode(body.password()), autoApprove);
            return ResponseEntity.status(HttpStatus.CREATED).body(Map.of("id", id));
        } catch (DuplicateKeyException e) {
            return conflict();
        }
    }

    private static ResponseEntity<Map<String, Object>> conflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("message", "이미 사용 중인 이메일입니다."));
    }

    private static ResponseEntity<Map<String, Object>> unauthorized(String message) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("message", message));
    }

    private static ResponseCookie refreshCookie(String value, Duration maxAge) {
        return ResponseCookie.from(REFRESH_COOKIE, value)
                .httpOnly(true)
                .secure(true)
                .sameSite("Strict")
                .path("/")
                .maxAge(maxAge)
                .build();
    }
}
