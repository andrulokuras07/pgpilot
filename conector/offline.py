"""Modo offline del conector.

B6 del backlog. Permite que PgPilot opere sin conexión viva a la BD
del cliente. Es feature de venta para empresas que no quieren
conceder acceso de red a su Postgres productivo.

**Decisión técnica (ver PROGRESS.md 2026-05-09):** el backlog
original sugiere parsear `pg_dump --schema-only` + un export CSV de
`pg_stats`. En la práctica:

- pg_dump emite SQL específico de Postgres (ALTER TABLE OWNER, SET
  SESSION, COMMENT ON, extensions) que sqlglot no parsea fielmente.
- pg_stats tiene `most_common_vals::anyarray` que requiere lógica
  custom para interpretar tipo por tipo.

Implementarlo bien requiere su propio ticket. Mientras tanto, B6
acepta un "metadata bundle" en JSON con la misma forma del cache
(B5). El cliente ejecuta `export_bundle()` en su entorno (con
acceso a su BD), nos comparte el archivo, y nosotros cargamos con
`load_bundle()`. La BD del cliente nunca habla con nuestra
infraestructura.

El bundle es portable y autoexplicativo (incluye fingerprint origen,
hash, fecha, lista de schemas).
"""

import json
from pathlib import Path

from psycopg_pool import ConnectionPool

from conector.cache import (
    CacheFile,
    compute_content_hash,
    compute_fingerprint,
    extract_snapshot,
)
from conector.types import SchemaSnapshot


def export_bundle(
    pool: ConnectionPool,
    path: Path,
    schemas: tuple[str, ...] = ("public",),
    *,
    host: str,
    port: int,
    dbname: str,
) -> Path:
    """Extrae snapshot y lo escribe a `path` como bundle JSON portable.

    Ejecuta lo mismo que `extract_snapshot` y serializa con la misma
    forma que el cache de B5. El cliente corre esta función en su
    entorno y nos comparte el archivo resultante.

    `host`, `port`, `dbname` se reciben explícitos (en lugar de leerlos
    del pool) para no acoplarse a la API interna de psycopg_pool y
    para que el bundle pueda anonimizar (ej. dbname="redacted") si el
    cliente lo prefiere.

    Devuelve la ruta escrita.
    """
    snapshot = extract_snapshot(pool, schemas)
    payload: CacheFile = {
        "fingerprint": compute_fingerprint(host, port, dbname, schemas),
        "content_hash": compute_content_hash(snapshot),
        "extracted_at": _now_iso(),
        "schemas": list(schemas),
        "snapshot": snapshot,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_bundle(path: Path) -> SchemaSnapshot:
    """Carga un bundle producido por `export_bundle` y devuelve el snapshot.

    El llamador puede usar el `SchemaSnapshot` directamente con el resto
    del producto (motor, recomendador) sin distinguirlo de uno extraído
    en vivo: misma forma de dict, mismas claves.

    Si quieres validar la integridad del bundle, recalcula el hash y
    compáralo con el campo `content_hash` del archivo (ver
    `validate_bundle`).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["snapshot"]


def validate_bundle(path: Path) -> bool:
    """Verifica que `content_hash` del bundle coincide con el snapshot
    serializado actualmente. Útil para detectar tampering o corrupción
    en tránsito.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot: SchemaSnapshot = payload["snapshot"]
    return compute_content_hash(snapshot) == payload["content_hash"]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
