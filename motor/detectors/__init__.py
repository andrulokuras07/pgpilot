"""Detectores de anti-patterns. Cada submódulo expone una función
`detect_<nombre>(plan, snapshot) -> Detection`."""

from motor.detectors.correlated_subquery import detect_correlated_subquery
from motor.detectors.function_in_where import detect_function_in_where
from motor.detectors.like_leading_wildcard import detect_like_leading_wildcard
from motor.detectors.missing_covering_index import detect_missing_covering_index
from motor.detectors.nested_loop_large_outer import detect_nested_loop_large_outer
from motor.detectors.or_across_tables import detect_or_across_tables
from motor.detectors.select_star import detect_select_star
from motor.detectors.seq_scan_on_large_table import detect_seq_scan_on_large_table

__all__ = [
    "detect_seq_scan_on_large_table",
    "detect_like_leading_wildcard",
    "detect_function_in_where",
    "detect_or_across_tables",
    "detect_correlated_subquery",
    "detect_nested_loop_large_outer",
    "detect_select_star",
    "detect_missing_covering_index",
]
