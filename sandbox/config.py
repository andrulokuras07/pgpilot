"""Configuración del sandbox Postgres efímero.

Espejo de `conector/config.py`, separado a propósito:
- El sandbox es BD propia de PgPilot, no del cliente, así que el pool
  NO va a ser read-only (R7 no aplica). Mantener la config aparte
  evita confusiones entre ambos pools.
- Las credenciales del sandbox suelen ser distintas a las de la BD
  analizada y no deberían reusarse.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    statement_timeout_ms: int = 5000
    min_pool_size: int = 1
    max_pool_size: int = 4
