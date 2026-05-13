"""Detectores de anti-patterns. Cada submódulo expone una función
`detect_<nombre>(plan, snapshot) -> Detection`."""

from motor.detectors.cardinality_misestimate import detect_cardinality_misestimate
from motor.detectors.correlated_subquery import detect_correlated_subquery
from motor.detectors.function_in_where import detect_function_in_where
from motor.detectors.having_without_aggregate import detect_having_without_aggregate
from motor.detectors.in_subquery_to_exists import detect_in_subquery_to_exists
from motor.detectors.like_leading_wildcard import detect_like_leading_wildcard
from motor.detectors.missing_covering_index import detect_missing_covering_index
from motor.detectors.missing_index import detect_missing_index
from motor.detectors.nested_loop_large_outer import detect_nested_loop_large_outer
from motor.detectors.or_across_tables import detect_or_across_tables
from motor.detectors.partial_index_opportunity import detect_partial_index_opportunity
from motor.detectors.select_star import detect_select_star
from motor.detectors.seq_scan_on_large_table import detect_seq_scan_on_large_table
from motor.detectors.sort_spill_to_disk import detect_sort_spill_to_disk
from motor.detectors.stale_statistics import detect_stale_statistics
from motor.detectors.type_mismatch import detect_type_mismatch
from motor.detectors.unnecessary_cte_materialize import (
    detect_unnecessary_cte_materialize,
)

__all__ = [
    "detect_seq_scan_on_large_table",
    "detect_stale_statistics",
    "detect_sort_spill_to_disk",
    "detect_like_leading_wildcard",
    "detect_function_in_where",
    "detect_or_across_tables",
    "detect_correlated_subquery",
    "detect_nested_loop_large_outer",
    "detect_select_star",
    "detect_missing_covering_index",
    "detect_type_mismatch",
    "detect_unnecessary_cte_materialize",
    "detect_missing_index",
    "detect_partial_index_opportunity",
    "detect_cardinality_misestimate",
    "detect_having_without_aggregate",
    "detect_in_subquery_to_exists",
]
