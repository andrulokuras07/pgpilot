from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    statement_timeout_ms: int = 5000
    min_pool_size: int = 1
    max_pool_size: int = 4
