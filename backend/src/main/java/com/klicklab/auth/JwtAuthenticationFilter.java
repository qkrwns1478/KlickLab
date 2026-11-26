package com.klicklab.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/** Authorization: Bearer {token} 검증 후 SecurityContext 에 AuthUser 를 설정 */
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    /** 토큰이 있었지만 유효하지 않은 경우 표시 (401 메시지 구분용) */
    public static final String INVALID_TOKEN_ATTRIBUTE = JwtAuthenticationFilter.class.getName() + ".INVALID";

    private final JwtService jwtService;

    public JwtAuthenticationFilter(JwtService jwtService) {
        this.jwtService = jwtService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header != null && header.startsWith("Bearer ")) {
            String token = header.substring(7).trim();
            jwtService.parseAccessToken(token).ifPresentOrElse(
                    user -> SecurityContextHolder.getContext().setAuthentication(
                            UsernamePasswordAuthenticationToken.authenticated(user, null, List.of())),
                    () -> request.setAttribute(INVALID_TOKEN_ATTRIBUTE, Boolean.TRUE));
        }
        chain.doFilter(request, response);
    }
}
