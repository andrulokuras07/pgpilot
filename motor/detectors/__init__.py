"""Detectores de anti-patterns. Cada submódulo expone una función
`detect_<nombre>(plan, snapshot) -> Detection`."""

from motor.detectors.cardinality_misestimate import detect_cardinality_misestimate
from motor.detectors.correlated_subquery import detect_correlated_subquery
from motor.detectors.function_in_where import detect_function_in_where
from motor.detectors.like_leading_wildcard import detect_like_leading_wildcard
from motor.detectors.missing_index import detect_missing_index
from motor.detectors.or_across_tables import detect_or_across_tables
from motor.detectors.partial_index_opportunity import detect_partial_index_opportunity
from motor.detectors.seq_scan_on_large_table import detect_seq_scan_on_large_table

__all__ = [
    "detect_seq_scan_on_large_table",
    "detect_like_leading_wildcard",
    "detect_function_in_where",
    "detect_or_across_tables",
    "detect_correlated_subquery",
    "detect_missing_index",
    "detect_partial_index_opportunity",
    "detect_cardinality_misestimate",
]
