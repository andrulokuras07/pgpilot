"""Tests para `get_column_stats` (B4).

La mayoría son de integración: requieren AppDB v1 corriendo en
`localhost:5434` y con `ANALYZE` ejecutado al menos una vez (el seed
de AppDB lo ejecuta al final de `02_seed_data.sql`).
"""

import pytest
from psycopg_pool import ConnectionPool

from conector import get_column_stats


@pytest.mark.integration
def test_devuelve_entrada_para_cada_tabla_de_appdb(appdb_pool: ConnectionPool) -> None:
    stats = get_column_stats(appdb_pool)

    expected_tables = {
        "public.users",
        "public.posts",
        "public.comments",
        "public.likes",
        "public.follows",
        "public.notifications",
        "public.tags",
        "public.post_tags",
    }
    assert expected_tables.issubset(set(stats.keys()))


@pytest.mark.integration
def test_users_id_tiene_n_distinct_alto(appdb_pool: ConnectionPool) -> None:
    """`users.id` es PK serial: tras ANALYZE su n_distinct debe reflejar
    casi 1 valor distinto por fila (positivo grande o -1.0).

    Si AppDB nunca corrió ANALYZE, el test queda inconcluso (skip).
    """
    stats = get_column_stats(appdb_pool)
    users_id = stats["public.users"]["id"]

    if not users_id["has_stats"]:
        pytest.skip("users.id sin ANALYZE; no se puede validar n_distinct")

    n = users_id["n_distinct"]
    assert n is not None
    # Conteo absoluto grande O ratio cercano a -1 (todos distintos).
    assert n >= 1000 or n <= -0.9


@pytest.mark.integration
def test_columnas_de_cada_tabla_estan_completas(appdb_pool: ConnectionPool) -> None:
    """Toda columna de pg_attribute aparece en el resultado, tenga o no
    estadísticas. Esto es lo que nos permite distinguir 'sin ANALYZE'
    de 'columna inexistente'."""
    stats = get_column_stats(appdb_pool)

    posts_cols = set(stats["public.posts"].keys())
    expected_cols = {
        "id",
        "author_id",
        "content",
        "mentioned_user_id",
        "media_url",
        "likes_count",
        "comments_count",
        "is_deleted",
        "created_at",
    }
    assert expected_cols.issubset(posts_cols)


@pytest.mark.integration
def test_null_frac_en_rango_valido(appdb_pool: ConnectionPool) -> None:
    """`null_frac` debe estar en [0,1] para toda columna con stats."""
    stats = get_column_stats(appdb_pool)

    for table_stats in stats.values():
        for col_stats in table_stats.values():
            if not col_stats["has_stats"]:
                continue
            null_frac = col_stats["null_frac"]
            assert null_frac is not None
            assert 0.0 <= null_frac <= 1.0


@pytest.mark.integration
def test_correlation_en_rango_valido(appdb_pool: ConnectionPool) -> None:
    """`correlation` debe estar en [-1, 1] para toda columna con stats."""
    stats = get_column_stats(appdb_pool)

    for table_stats in stats.values():
        for col_stats in table_stats.values():
            if not col_stats["has_stats"]:
                continue
            corr = col_stats["correlation"]
            # Para tipos no ordenables (jsonb, etc.) Postgres puede dejar
            # correlation en NULL aun con has_stats=True.
            if corr is None:
                continue
            assert -1.0 <= corr <= 1.0


@pytest.mark.integration
def test_columna_sin_stats_devuelve_none(appdb_pool: ConnectionPool) -> None:
    """Si una columna no tiene fila en pg_stats, los campos numéricos
    son None y has_stats=False. Garantiza el contrato del backlog
    'valor explícito de sin estadísticas'."""
    stats = get_column_stats(appdb_pool)

    # Recorremos todo y verificamos invariante: has_stats=False ⇒ todos None.
    found_any = False
    for table_stats in stats.values():
        for col_stats in table_stats.values():
            if not col_stats["has_stats"]:
                found_any = True
                assert col_stats["n_distinct"] is None
                assert col_stats["null_frac"] is None
                assert col_stats["most_common_vals"] is None
                assert col_stats["correlation"] is None

    # Nota: con AppDB v1 sembrada y ANALYZE-ada, este caso puede no
    # aparecer. El test no falla si no hay columnas sin stats; solo
    # fallaría si alguna tiene has_stats=False con campos no-None.
    _ = found_any


@pytest.mark.integration
def test_keys_compatibles_con_get_schema(appdb_pool: ConnectionPool) -> None:
    """Las claves '<schema>.<tabla>' deben coincidir con get_schema
    para que /motor pueda intersectar sin transformaciones."""
    from conector import get_schema

    schema = get_schema(appdb_pool)
    stats = get_column_stats(appdb_pool)

    schema_tables = set(schema.keys())
    stats_tables = set(stats.keys())
    assert schema_tables == stats_tables

    # Y dentro de cada tabla, los nombres de columna deben ser superset
    # (pg_attribute es la fuente; get_schema podría omitir alguna,
    # aunque no debería).
    for key in schema_tables:
        schema_cols = {c["name"] for c in schema[key]["columns"]}
        stats_cols = set(stats[key].keys())
        assert schema_cols.issubset(stats_cols)
