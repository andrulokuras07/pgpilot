"""Tests de `ia.sanitizer`.

Tests unitarios sin marker `integration`: no requieren AppDB ni Docker.
Misma convención que `tests/motor/` (ver PROGRESS 2026-05-09).
"""

from ia import restore, sanitize

# --- Criterio de "hecho cuando" del backlog ---


def test_query_con_email_real_no_aparece_en_output():
    sql = "SELECT * FROM users WHERE email = 'juan@empresa.com'"
    result = sanitize(sql)
    assert "juan@empresa.com" not in result.sql
    assert "$LITERAL_" in result.sql


def test_query_con_rfc_mexicano_no_aparece_en_output():
    # RFC mexicano persona física: 4 letras + 6 dígitos + 3 alfanuméricos.
    # Va dentro de un string SQL; el patrón `string` lo cubre.
    sql = "SELECT * FROM clientes WHERE rfc = 'GODE561231GR8'"
    result = sanitize(sql)
    assert "GODE561231GR8" not in result.sql


# --- Cobertura por tipo de literal ---


def test_sanitiza_string_simple():
    sql = "SELECT * FROM t WHERE name = 'Ana'"
    result = sanitize(sql)
    assert "'Ana'" not in result.sql
    assert any(v["type"] == "string" for v in result.literals.values())


def test_sanitiza_numero_entero():
    sql = "SELECT * FROM orders WHERE id = 12345"
    result = sanitize(sql)
    assert "12345" not in result.sql
    assert any(v["type"] == "number" for v in result.literals.values())


def test_sanitiza_numero_decimal():
    sql = "SELECT * FROM products WHERE price > 99.95"
    result = sanitize(sql)
    assert "99.95" not in result.sql


def test_sanitiza_uuid():
    sql = "SELECT * FROM t WHERE id = 550e8400-e29b-41d4-a716-446655440000"
    result = sanitize(sql)
    assert "550e8400-e29b-41d4-a716-446655440000" not in result.sql
    assert any(v["type"] == "uuid" for v in result.literals.values())


def test_sanitiza_fecha_iso():
    sql = "SELECT * FROM logs WHERE created_at >= 2026-05-09"
    result = sanitize(sql)
    assert "2026-05-09" not in result.sql
    assert any(v["type"] == "date" for v in result.literals.values())


def test_sanitiza_fecha_iso_con_hora():
    sql = "SELECT * FROM logs WHERE created_at >= 2026-05-09T14:30:00"
    result = sanitize(sql)
    assert "2026-05-09" not in result.sql


def test_sanitiza_email_fuera_de_string():
    sql = "SELECT * FROM t WHERE col = juan@empresa.com"
    result = sanitize(sql)
    assert "juan@empresa.com" not in result.sql
    assert any(v["type"] == "email" for v in result.literals.values())


# --- Lo que NO debe sanitizar ---


def test_no_sanitiza_keywords_sql():
    sql = "SELECT * FROM users WHERE active = TRUE"
    result = sanitize(sql)
    assert "SELECT" in result.sql
    assert "FROM" in result.sql
    assert "WHERE" in result.sql


def test_no_sanitiza_nombres_de_tablas_y_columnas():
    sql = "SELECT name, email FROM users WHERE id = 1"
    result = sanitize(sql)
    assert "users" in result.sql
    assert "name" in result.sql
    assert "email" in result.sql


def test_query_sin_literales_no_cambia():
    sql = "SELECT * FROM users"
    result = sanitize(sql)
    assert result.sql == sql
    assert result.literals == {}


# --- Mapa de retorno ---


def test_mapa_contiene_tipo_y_original():
    sql = "SELECT * FROM t WHERE id = 42"
    result = sanitize(sql)
    valores = list(result.literals.values())
    assert len(valores) == 1
    assert valores[0]["type"] == "number"
    assert valores[0]["original"] == "42"


def test_placeholders_separados_por_tipo():
    sql = "SELECT * FROM t WHERE name = 'Ana' AND age = 30"
    result = sanitize(sql)
    # string usa sufijo 1, number usa sufijo 2 (según backlog)
    assert "$LITERAL_1_" in result.sql  # primer string
    assert "$LITERAL_2_" in result.sql  # primer número


# --- Roundtrip ---


def test_restore_reconstruye_query_original():
    original = "SELECT * FROM users WHERE id = 42 AND name = 'Ana'"
    sanitized = sanitize(original)
    assert restore(sanitized) == original


def test_restore_con_muchos_literales():
    original = (
        "SELECT * FROM orders "
        "WHERE user_id = 1 AND total > 99.50 "
        "AND created_at >= '2026-01-01' AND email = 'admin@test.mx'"
    )
    sanitized = sanitize(original)
    assert restore(sanitized) == original


# --- Casos compuestos ---


def test_query_compleja_con_join_y_multiples_literales():
    sql = (
        "SELECT u.name, o.total FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "WHERE u.email = 'admin@test.mx' "
        "AND o.created_at >= '2026-01-01' "
        "AND o.total > 1000.50"
    )
    result = sanitize(sql)
    assert "admin@test.mx" not in result.sql
    assert "2026-01-01" not in result.sql
    assert "1000.50" not in result.sql
    assert "users" in result.sql
    assert "orders" in result.sql
    assert "JOIN" in result.sql


def test_string_con_comilla_escapada_se_consume_completo():
    # En SQL, 'it''s' es un solo literal con una comilla interna.
    sql = "SELECT * FROM notes WHERE body = 'it''s ok'"
    result = sanitize(sql)
    assert "it''s ok" not in result.sql
    # Un solo placeholder, no dos
    assert result.sql.count("$LITERAL_") == 1
