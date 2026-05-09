"""Tipos compartidos entre módulos del conector.

Aislados aquí para evitar dependencias circulares entre `cache.py`
y `offline.py`, ambos consumen `SchemaSnapshot`.
"""

from typing import TypedDict

from conector.schema import TableSchema
from conector.sizes import TableSize
from conector.stats import ColumnStats


class SchemaSnapshot(TypedDict):
    """Snapshot consolidado de una BD: schema + tamaños + estadísticas.

    Producido por `extract_snapshot` y persistido por el cache (B5) y
    por el modo offline (B6). Mismo formato en disco para ambos.

    Las claves de `schema` y `sizes` son `"<schema>.<tabla>"`. Las
    claves de `stats` también, con un nivel adicional por nombre de
    columna.
    """

    schema: dict[str, TableSchema]
    sizes: dict[str, TableSize]
    stats: dict[str, dict[str, ColumnStats]]
