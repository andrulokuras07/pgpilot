"""Tests de integración para `get_schema`.

Requieren AppDB v1 corriendo en `localhost:5434` (ver
`tests/conector/conftest.py`).
"""

import pytest
from psycopg_pool import ConnectionPool

from conector import get_schema


@pytest.mark.integration
def test_extrae_todas_las_tablas_de_appdb(appdb_pool: ConnectionPool) -> None:
    schema = get_schema(appdb_pool)

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
    assert expected_tables.issubset(set(schema.keys()))


@pytest.mark.integration
def test_columnas_de_users_correctas(appdb_pool: ConnectionPool) -> None:
    schema = get_schema(appdb_pool)
    users = schema["public.users"]

    column_names = {c["name"] for c in users["columns"]}
    assert {"id", "username", "email", "is_verified", "created_at"}.issubset(column_names)

    by_name = {c["name"]: c for c in users["columns"]}
    assert by_name["id"]["data_type"] == "integer"
    assert by_name["id"]["is_nullable"] is False
    assert by_name["bio"]["is_nullable"] is True


@pytest.mark.integration
def test_indices_se_extraen_con_columnas_y_metodo(appdb_pool: ConnectionPool) -> None:
    schema = get_schema(appdb_pool)
    posts = schema["public.posts"]

    indexes_by_name = {idx["name"]: idx for idx in posts["indexes"]}

    # Cualquier índice declarado en init/01_schema.sql sin método explícito
    # debe ser btree.
    assert "idx_posts_created_at" in indexes_by_name
    assert indexes_by_name["idx_posts_created_at"]["columns"] == ["created_at"]
    assert indexes_by_name["idx_posts_created_at"]["method"] == "btree"
    assert indexes_by_name["idx_posts_created_at"]["is_primary"] is False

    # PK de posts debe aparecer marcado is_primary y is_unique.
    primary = [idx for idx in posts["indexes"] if idx["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["columns"] == ["id"]
    assert primary[0]["is_unique"] is True


@pytest.mark.integration
def test_seq_scan_target_no_tiene_indice_en_author_id(
    appdb_pool: ConnectionPool,
) -> None:
    """`posts.author_id` está sin índice por diseño (Q01 plantada).

    Este test verifica que el extractor refleja correctamente esa
    ausencia, que es la señal que el detector de seq scan va a usar.
    """
    schema = get_schema(appdb_pool)
    posts = schema["public.posts"]

    indexed_columns = {col for idx in posts["indexes"] for col in idx["columns"]}
    assert "author_id" not in indexed_columns


@pytest.mark.integration
def test_foreign_keys_de_comments(appdb_pool: ConnectionPool) -> None:
    schema = get_schema(appdb_pool)
    comments = schema["public.comments"]

    fks_by_columns = {tuple(fk["columns"]): fk for fk in comments["foreign_keys"]}

    assert ("post_id",) in fks_by_columns
    assert fks_by_columns[("post_id",)]["referenced_table"] == "posts"
    assert fks_by_columns[("post_id",)]["referenced_columns"] == ["id"]

    assert ("author_id",) in fks_by_columns
    assert fks_by_columns[("author_id",)]["referenced_table"] == "users"


@pytest.mark.integration
def test_indice_compuesto_de_post_tags(appdb_pool: ConnectionPool) -> None:
    """post_tags tiene PK compuesta (post_id, tag_id) — el orden importa
    para que un detector futuro decida si un índice cubre un filtro."""
    schema = get_schema(appdb_pool)
    post_tags = schema["public.post_tags"]

    primary = [idx for idx in post_tags["indexes"] if idx["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["columns"] == ["post_id", "tag_id"]


@pytest.mark.integration
def test_schema_filter_excluye_pg_catalog(appdb_pool: ConnectionPool) -> None:
    schema = get_schema(appdb_pool, schemas=("public",))
    for key in schema:
        assert key.startswith("public.")
