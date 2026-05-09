"""Tests para B5 (cache de metadata).

Mezcla unit tests de las funciones puras (`compute_fingerprint`,
`compute_content_hash`) con tests de integración que verifican el
ciclo extract → save → load contra AppDB.
"""

import time
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from conector import (
    SchemaSnapshot,
    compute_content_hash,
    compute_fingerprint,
    extract_snapshot,
    get_snapshot,
    invalidate_cache,
    load_snapshot,
    save_snapshot,
)


def test_fingerprint_es_deterministico() -> None:
    a = compute_fingerprint("localhost", 5434, "appdb", ("public",))
    b = compute_fingerprint("localhost", 5434, "appdb", ("public",))
    assert a == b
    assert len(a) == 32  # md5 hex


def test_fingerprint_distinto_si_cambia_cualquier_parte() -> None:
    base = compute_fingerprint("localhost", 5434, "appdb", ("public",))
    assert base != compute_fingerprint("otro_host", 5434, "appdb", ("public",))
    assert base != compute_fingerprint("localhost", 5435, "appdb", ("public",))
    assert base != compute_fingerprint("localhost", 5434, "otra_db", ("public",))
    assert base != compute_fingerprint("localhost", 5434, "appdb", ("public", "audit"))


def test_fingerprint_no_depende_del_orden_de_schemas() -> None:
    a = compute_fingerprint("localhost", 5434, "appdb", ("public", "audit"))
    b = compute_fingerprint("localhost", 5434, "appdb", ("audit", "public"))
    assert a == b


def test_content_hash_es_estable_entre_llamadas() -> None:
    snapshot: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    assert compute_content_hash(snapshot) == compute_content_hash(snapshot)


def test_content_hash_cambia_si_cambia_contenido() -> None:
    s1: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    s2: SchemaSnapshot = {
        "schema": {
            "public.x": {
                "schema": "public",
                "name": "x",
                "columns": [],
                "indexes": [],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }
    assert compute_content_hash(s1) != compute_content_hash(s2)


def test_save_y_load_roundtrip(tmp_path: Path) -> None:
    """save_snapshot + load_snapshot devuelve el mismo dict (sin BD)."""
    snapshot: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    fingerprint = "test_fp_1234"

    save_snapshot(snapshot, fingerprint, cache_dir=tmp_path)
    loaded = load_snapshot(fingerprint, cache_dir=tmp_path)

    assert loaded == snapshot


def test_load_snapshot_sin_archivo_devuelve_none(tmp_path: Path) -> None:
    assert load_snapshot("inexistente", cache_dir=tmp_path) is None


def test_invalidate_cache_borra_solo_un_fingerprint(tmp_path: Path) -> None:
    snap: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    save_snapshot(snap, "a", cache_dir=tmp_path)
    save_snapshot(snap, "b", cache_dir=tmp_path)

    deleted = invalidate_cache(cache_dir=tmp_path, fingerprint="a")

    assert deleted == 1
    assert load_snapshot("a", cache_dir=tmp_path) is None
    assert load_snapshot("b", cache_dir=tmp_path) is not None


def test_invalidate_cache_completo(tmp_path: Path) -> None:
    snap: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    save_snapshot(snap, "a", cache_dir=tmp_path)
    save_snapshot(snap, "b", cache_dir=tmp_path)

    deleted = invalidate_cache(cache_dir=tmp_path)

    assert deleted == 2
    assert load_snapshot("a", cache_dir=tmp_path) is None
    assert load_snapshot("b", cache_dir=tmp_path) is None


def test_invalidate_cache_inexistente_no_falla(tmp_path: Path) -> None:
    # Directorio que no existe.
    assert invalidate_cache(tmp_path / "nope") == 0
    # Fingerprint que no existe en directorio que sí.
    assert invalidate_cache(tmp_path, fingerprint="inexistente") == 0


@pytest.mark.integration
def test_extract_snapshot_combina_b2_b3_b4(appdb_pool: ConnectionPool) -> None:
    snap = extract_snapshot(appdb_pool)

    assert "public.users" in snap["schema"]
    assert "public.users" in snap["sizes"]
    assert "public.users" in snap["stats"]

    # Las claves de tabla son consistentes entre las tres dimensiones.
    assert set(snap["schema"].keys()) == set(snap["sizes"].keys())
    assert set(snap["schema"].keys()) == set(snap["stats"].keys())


@pytest.mark.integration
def test_get_snapshot_segunda_llamada_tarda_menos_de_100ms(
    appdb_pool: ConnectionPool, tmp_path: Path
) -> None:
    """Criterio del backlog: 'la segunda extracción consecutiva tarda
    menos de 100ms'."""
    fingerprint = "appdb_test_perf"

    # Primera llamada: extrae y persiste. No medimos esta.
    snapshot1 = get_snapshot(appdb_pool, fingerprint=fingerprint, cache_dir=tmp_path)

    # Segunda llamada: debe leer del cache.
    start = time.perf_counter()
    snapshot2 = get_snapshot(appdb_pool, fingerprint=fingerprint, cache_dir=tmp_path)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert snapshot1 == snapshot2
    assert elapsed_ms < 100, f"Cache hit tardó {elapsed_ms:.1f}ms (>100ms)"


@pytest.mark.integration
def test_get_snapshot_force_refresh_ignora_cache(
    appdb_pool: ConnectionPool, tmp_path: Path
) -> None:
    fingerprint = "appdb_test_refresh"

    # Plantamos un snapshot vacío en el cache.
    fake: SchemaSnapshot = {"schema": {}, "sizes": {}, "stats": {}}
    save_snapshot(fake, fingerprint, cache_dir=tmp_path)

    # force_refresh debe ignorarlo y traer datos reales.
    snap = get_snapshot(
        appdb_pool,
        fingerprint=fingerprint,
        cache_dir=tmp_path,
        force_refresh=True,
    )

    assert "public.users" in snap["schema"]
    # Y el cache quedó actualizado.
    reloaded = load_snapshot(fingerprint, cache_dir=tmp_path)
    assert reloaded is not None
    assert "public.users" in reloaded["schema"]


@pytest.mark.integration
def test_get_snapshot_sin_fingerprint_no_toca_disco(
    appdb_pool: ConnectionPool, tmp_path: Path
) -> None:
    """Sin fingerprint, get_snapshot extrae siempre y no escribe nada."""
    snap = get_snapshot(appdb_pool, cache_dir=tmp_path)

    assert "public.users" in snap["schema"]
    assert list(tmp_path.glob("*.json")) == []
