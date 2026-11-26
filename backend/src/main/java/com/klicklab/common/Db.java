package com.klicklab.common;

import org.postgresql.util.PGobject;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.sql.Array;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 분석 쿼리용 얇은 JDBC 래퍼.
 *
 * <p>조회 결과를 JSON 친화적인 값으로 변환한다
 * (DATE → "yyyy-MM-dd", TIMESTAMPTZ → "yyyy-MM-dd HH:mm:ss", NUMERIC → long/double, ARRAY → List).
 * 기존 ClickHouse JSON 응답과 동일한 형태를 유지하기 위함.</p>
 */
@Component
public class Db {

    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final NamedParameterJdbcTemplate jdbc;
    private final ZoneId zone;
    private final RowMapper<Map<String, Object>> rowMapper = this::mapRow;

    public Db(NamedParameterJdbcTemplate jdbc, AppClock clock) {
        this.jdbc = jdbc;
        this.zone = clock.zone();
    }

    /** key, value, key, value ... 형태로 파라미터를 만든다 (null 허용). */
    public static MapSqlParameterSource params(Object... keyValues) {
        if (keyValues.length % 2 != 0) {
            throw new IllegalArgumentException("params must be key/value pairs");
        }
        MapSqlParameterSource source = new MapSqlParameterSource();
        for (int i = 0; i < keyValues.length; i += 2) {
            source.addValue((String) keyValues[i], keyValues[i + 1]);
        }
        return source;
    }

    public List<Map<String, Object>> list(String sql, SqlParameterSource params) {
        return jdbc.query(sql, params, rowMapper);
    }

    /** 첫 행 (없으면 빈 Map) */
    public Map<String, Object> one(String sql, SqlParameterSource params) {
        List<Map<String, Object>> rows = list(sql, params);
        return rows.isEmpty() ? new LinkedHashMap<>() : rows.getFirst();
    }

    /** 첫 행 첫 컬럼을 long 으로 (없거나 NULL 이면 0) */
    public long longValue(String sql, SqlParameterSource params) {
        Map<String, Object> row = one(sql, params);
        return row.isEmpty() ? 0L : Values.toLong(row.values().iterator().next());
    }

    public int update(String sql, SqlParameterSource params) {
        return jdbc.update(sql, params);
    }

    private Map<String, Object> mapRow(java.sql.ResultSet rs, int rowNum) throws SQLException {
        ResultSetMetaData meta = rs.getMetaData();
        int count = meta.getColumnCount();
        Map<String, Object> row = new LinkedHashMap<>(count * 2);
        for (int i = 1; i <= count; i++) {
            row.put(meta.getColumnLabel(i), convert(rs.getObject(i)));
        }
        return row;
    }

    private Object convert(Object value) throws SQLException {
        return switch (value) {
            case null -> null;
            case java.sql.Date d -> d.toLocalDate().toString();
            case Timestamp t -> t.toInstant().atZone(zone).format(DATE_TIME);
            case OffsetDateTime o -> o.atZoneSameInstant(zone).format(DATE_TIME);
            case BigDecimal b -> normalize(b);
            case Array a -> {
                Object[] items = (Object[]) a.getArray();
                List<Object> list = new ArrayList<>(items.length);
                for (Object item : items) {
                    list.add(convert(item));
                }
                yield list;
            }
            case PGobject p -> p.getValue();
            case UUID u -> u.toString();
            default -> value;
        };
    }

    private static Object normalize(BigDecimal b) {
        BigDecimal stripped = b.stripTrailingZeros();
        if (stripped.scale() <= 0 && stripped.abs().compareTo(BigDecimal.valueOf(Long.MAX_VALUE)) <= 0) {
            return stripped.longValue();
        }
        return b.doubleValue();
    }
}
