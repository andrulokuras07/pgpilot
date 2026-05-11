"""Detectores de anti-patterns. Cada submódulo expone una función
`detect_<nombre>(plan, snapshot) -> Detection`."""

from motor.detectors.seq_scan_on_large_table import detect_seq_scan_on_large_table

__all__ = ["detect_seq_scan_on_large_table"]
