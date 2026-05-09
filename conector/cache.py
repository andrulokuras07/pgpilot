"""Cache de metadata por hash, modo offline-friendly.

B5 del backlog. La extracción de schema + tamaños + stats contra una
BD del cliente puede tardar segundos sobre BDs grandes y no tiene por
qué repetirse en cada análisis. Este módulo:

1. Combina B2 (`get_schema`), B3 (`get_table_sizes`) y B4
   (`get_column_stats`) en un único `SchemaSnapshot`.
2. Calcula un `content_hash` (md5 del snapshot serializado en JSON
   canónico) para detectar drift entre extracciones.
3. Persiste el snapshot en `cache/{fingerprint}.json` donde
   `fingerprint = md5(host:port:dbname:schemas)` identifica la BD,
   no el contenido.

**Desviación del backlog:** el backlog literal dice
`cache/{hash}.json` con hash del contenido. Eso requeriría re-extraer
para saber qué archivo leer (circular). Cambiamos el nombre del
archivo a `fingerprint` (identidad de la BD) y guardamos
`content_hash` dentro del JSON para detección de drift. Mismo
objetivo (lookup local sub-100ms), implementación funcional.

El cache es interno: para que un cliente comparta metadata sin dar
acceso a su BD, ver `conector/offline.py` (B6).
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from psycopg_pool import ConnectionPool

from conector.schema import get_schema
from conector.sizes import get_table_sizes
from conector.stats import get_column_stats
from conector.types import SchemaSnapshot

DEFAULT_CACHE_DIR = Path("cache")


class CacheFile(TypedDict):
    """Forma serializada del cache en disco. También usada por B6."""

    fingerprint: str
    content_hash: str
    extracted_at: str  # ISO-8601 UTC
    schemas: list[str]
    snapshot: SchemaSnapshot


def compute_fingerprint(
    host: str,
    port: int,
    dbname: str,
    schemas: tuple[str, ...] = ("public",),
) -> str:
    """Hash determinístico de la identidad de la BD.

    Sirve como nombre de archivo del cache y como llave de lookup. Dos
    extracciones consecutivas contra la misma BD producen el mismo
    fingerprint, aunque la BD haya cambiado por dentro (drift se
    detecta con `content_hash`).
    """
    schemas_str = ",".join(sorted(schemas))
    raw = f"{host}:{port}:{dbname}:{schemas_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def compute_content_hash(snapshot: SchemaSnapshot) -> str:
    """Hash md5 del snapshot serializado canónicamente.

    Cambia si cualquier dato del snapshot cambia (schema, tamaños,
    stats). Útil para detectar que el cache quedó obsoleto.

    `sort_keys=True` y `default=str` garantizan que dos snapshots con
    los mismos datos produzcan el mismo hash, sin depender del orden
    de iteración de dicts.
    """
    canonical = json.dumps(snapshot, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def extract_snapshot(
    pool: ConnectionPool,
    schemas: tuple[str, ...] = ("public",),
) -> SchemaSnapshot:
    """Ejecuta B2 + B3 + B4 contra el pool y arma un `SchemaSnapshot`.

    Función pura desde el punto de vista del caller (no escribe a
    disco). Se separa de `get_snapshot` para permitir tests del cache
    sin BD.
    """
    return SchemaSnapshot(
        schema=get_schema(pool, schemas),
        sizes=get_table_sizes(pool, schemas),
        stats=get_column_stats(pool, schemas),
    )


def _cache_path(cache_dir: Path, fingerprint: str) -> Path:
    return cache_dir / f"{fingerprint}.json"


def save_snapshot(
    snapshot: SchemaSnapshot,
    fingerprint: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    schemas: tuple[str, ...] = ("public",),
) -> Path:
    """Persiste el snapshot en `cache_dir/{fingerprint}.json`.

    Crea el directorio si no existe. Devuelve la ruta escrita.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload: CacheFile = {
        "fingerprint": fingerprint,
        "content_hash": compute_content_hash(snapshot),
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schemas": list(schemas),
        "snapshot": snapshot,
    }
    path = _cache_path(cache_dir, fingerprint)
    path.write_text(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_snapshot(
    fingerprint: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> SchemaSnapshot | None:
    """Lee el snapshot cacheado para ese fingerprint, o `None` si no existe.

    No valida que la BD remota siga teniendo el mismo contenido. El
    caller que necesite garantía de frescura debe usar `force_refresh=True`
    en `get_snapshot`.
    """
    path = _cache_path(cache_dir, fingerprint)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["snapshot"]


def invalidate_cache(
    cache_dir: Path = DEFAULT_CACHE_DIR,
    fingerprint: str | None = None,
) -> int:
    """Borra archivos de cache. Devuelve cuántos archivos eliminó.

    - `fingerprint=None`: borra TODOS los `*.json` del directorio.
    - `fingerprint="abc..."`: borra solo `cache/abc....json`.

    No falla si el directorio o el archivo no existen.
    """
    if not cache_dir.exists():
        return 0

    if fingerprint is not None:
        path = _cache_path(cache_dir, fingerprint)
        if path.exists():
            path.unlink()
            return 1
        return 0

    deleted = 0
    for path in cache_dir.glob("*.json"):
        path.unlink()
        deleted += 1
    return deleted


def get_snapshot(
    pool: ConnectionPool,
    schemas: tuple[str, ...] = ("public",),
    *,
    fingerprint: str | None = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> SchemaSnapshot:
    """High-level: lee del cache si existe; si no, extrae y guarda.

    Si `fingerprint` es `None`, se omite el cache (siempre extrae).
    Esto permite usar la función como conveniencia incluso sin
    persistencia.

    `force_refresh=True` ignora el cache pero igual lo sobrescribe
    con el resultado fresco.
    """
    if fingerprint is None:
        return extract_snapshot(pool, schemas)

    if not force_refresh:
        cached = load_snapshot(fingerprint, cache_dir)
        if cached is not None:
            return cached

    snapshot = extract_snapshot(pool, schemas)
    save_snapshot(snapshot, fingerprint, cache_dir, schemas)
    return snapshot
