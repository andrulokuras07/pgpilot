"""Tests para B6 (modo offline).

Verifica que `export_bundle` produce un archivo cargable por
`load_bundle` y que el `SchemaSnapshot` resultante es indistinguible
del que produciría una extracción en vivo. Eso cumple el criterio del
backlog: 'el extractor produce el mismo dict de metadata desde un
dump que desde conexión viva'.
"""

import json
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from conector import export_bundle, extract_snapshot, load_bundle
from conector.offline import validate_bundle


@pytest.mark.integration
def test_export_y_load_devuelven_mismo_snapshot_que_extract(
    appdb_pool: ConnectionPool, tmp_path: Path
) -> None:
    bundle_path = tmp_path / "appdb_bundle.json"

    live = extract_snapshot(appdb_pool)
    export_bundle(
        appdb_pool,
        bundle_path,
        host="localhost",
        port=5434,
        dbname="appdb",
    )
    offline = load_bundle(bundle_path)

    assert offline["schema"].keys() == live["schema"].keys()
    assert offline["sizes"].keys() == live["sizes"].keys()
    assert offline["stats"].keys() == live["stats"].keys()

    # Comparación profunda: las dos extracciones contra la misma BD,
    # en el mismo segundo, deben ser idénticas (modulo `reltuples`
    # que puede fluctuar si hay autovacuum corriendo, pero AppDB en
    # docker está estable).
    assert offline["schema"] == live["schema"]


@pytest.mark.integration
def test_bundle_incluye_metadata_de_origen(appdb_pool: ConnectionPool, tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    export_bundle(
        appdb_pool,
        bundle_path,
        host="localhost",
        port=5434,
        dbname="appdb",
        schemas=("public",),
    )

    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert "fingerprint" in payload
    assert "content_hash" in payload
    assert "extracted_at" in payload
    assert payload["schemas"] == ["public"]
    assert "snapshot" in payload


@pytest.mark.integration
def test_validate_bundle_detecta_tampering(appdb_pool: ConnectionPool, tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    export_bundle(
        appdb_pool,
        bundle_path,
        host="localhost",
        port=5434,
        dbname="appdb",
    )

    assert validate_bundle(bundle_path) is True

    # Tampering: borramos una tabla del snapshot sin actualizar el hash.
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload["snapshot"]["schema"].pop("public.users", None)
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_bundle(bundle_path) is False


@pytest.mark.integration
def test_load_bundle_funciona_sin_pool(appdb_pool: ConnectionPool, tmp_path: Path) -> None:
    """El criterio de B6 es 'funcionar sin conexión'. Tras exportar el
    bundle, load_bundle debe operar puramente sobre el archivo, sin
    tocar ningún pool."""
    bundle_path = tmp_path / "bundle.json"
    export_bundle(
        appdb_pool,
        bundle_path,
        host="localhost",
        port=5434,
        dbname="appdb",
    )

    # No usamos appdb_pool aquí: simulamos al cliente que recibe el
    # archivo sin tener acceso a la BD.
    snap = load_bundle(bundle_path)

    assert "public.posts" in snap["schema"]
    assert "public.posts" in snap["sizes"]
    assert "public.posts" in snap["stats"]
