package com.klicklab.auth;

import com.klicklab.common.Db;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public class UserAccountRepository {

    public record UserAccount(String id, String email, String passwordHash, String sdkKey, boolean approved) {
        public AuthUser toAuthUser() {
            return new AuthUser(id, email, sdkKey);
        }
    }

    private final NamedParameterJdbcTemplate jdbc;

    public UserAccountRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<UserAccount> findByEmail(String email) {
        return jdbc.query("""
                        SELECT id, email, password_hash, sdk_key, is_approved
                        FROM users WHERE lower(email) = lower(:email)
                        LIMIT 1
                        """, Db.params("email", email),
                (rs, i) -> new UserAccount(
                        rs.getString("id"), rs.getString("email"), rs.getString("password_hash"),
                        rs.getString("sdk_key"), rs.getBoolean("is_approved")))
                .stream().findFirst();
    }

    /** @return 생성된 사용자 id */
    public String create(String email, String passwordHash, boolean approved) {
        return jdbc.queryForObject("""
                        INSERT INTO users (email, password_hash, sdk_key, is_approved)
                        VALUES (:email, :hash, :sdkKey, :approved)
                        RETURNING id::text
                        """,
                Db.params("email", email, "hash", passwordHash, "sdkKey", UUID.randomUUID().toString(),
                        "approved", approved),
                String.class);
    }
}
