"""Tests del parser de pg_stat_statements — E1."""

from __future__ import annotations

from workload import parse_pg_stat_statements


CSV_SAMPLE = """\
query,calls,total_exec_time,mean_exec_time,rows
SELECT * FROM users WHERE id = $1,500,2500.0,5.0,500
INSERT INTO logs VALUES ($1),10000,1000.0,0.1,10000
SELECT count(*) FROM orders,3,15000.0,5000.0,3
"""

JSON_SAMPLE = """[
  {"query": "SELECT * FROM users WHERE id = $1", "calls": 500, "total_exec_time": 2500.0, "mean_exec_time": 5.0, "rows": 500},
  {"query": "INSERT INTO logs VALUES ($1)", "calls": 10000, "total_exec_time": 1000.0, "mean_exec_time": 0.1, "rows": 10000},
  {"query": "SELECT count(*) FROM orders", "calls": 3, "total_exec_time": 15000.0, "mean_exec_time": 5000.0, "rows": 3}
]"""


def test_csv_parse_devuelve_tres_entries() -> None:
    entries = parse_pg_stat_statements(CSV_SAMPLE)
    assert len(entries) == 3


def test_csv_campos_correctos() -> None:
    entries = parse_pg_stat_statements(CSV_SAMPLE)
    e = entries[0]
    assert e.query == "SELECT * FROM users WHERE id = $1"
    assert e.calls == 500
    assert e.total_exec_time == 2500.0
    assert e.mean_exec_time == 5.0
    assert e.rows == 500


def test_json_parse_devuelve_tres_entries() -> None:
    entries = parse_pg_stat_statements(JSON_SAMPLE)
    assert len(entries) == 3


def test_json_campos_correctos() -> None:
    entries = parse_pg_stat_statements(JSON_SAMPLE)
    e = entries[2]
    assert e.query == "SELECT count(*) FROM orders"
    assert e.calls == 3
    assert e.total_exec_time == 15000.0


def test_vacio_devuelve_lista_vacia() -> None:
    assert parse_pg_stat_statements("") == []
    assert parse_pg_stat_statements("   ") == []


def test_csv_con_total_time_pg12() -> None:
    """PG < 13 usa total_time en vez de total_exec_time."""
    csv = "query,calls,total_time,mean_time,rows\nSELECT 1,10,100.0,10.0,10\n"
    entries = parse_pg_stat_statements(csv)
    assert len(entries) == 1
    assert entries[0].total_exec_time == 100.0
    assert entries[0].mean_exec_time == 10.0


def test_csv_50_queries() -> None:
    """E1 hecho-cuando: 50 queries parseadas correctamente."""
    lines = ["query,calls,total_exec_time,mean_exec_time,rows"]
    for i in range(50):
        lines.append(f"SELECT {i},1,{i * 10.0},{i * 10.0},1")
    csv = "\n".join(lines) + "\n"
    entries = parse_pg_stat_statements(csv)
    assert len(entries) == 50
