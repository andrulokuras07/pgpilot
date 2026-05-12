"""API pública del módulo `motor`.

Hoy: parser de EXPLAIN (B7+B8) y helper de búsqueda en el árbol (B9).
A medida que se agreguen detectores y recomendador, se exportan
desde aquí.
"""

from motor.detection import Detection
from motor.detectors import (
    detect_correlated_subquery,
    detect_function_in_where,
    detect_like_leading_wildcard,
    detect_or_across_tables,
    detect_seq_scan_on_large_table,
)
from motor.nodes import KNOWN_NODE_TYPES, find_nodes
from motor.parser import ExplainResult, PlanNode, parse_explain
from motor.recommender import Recommendation, recommend_for_seq_scan_on_large_table

__all__ = [
    "ExplainResult",
    "PlanNode",
    "parse_explain",
    "find_nodes",
    "KNOWN_NODE_TYPES",
    "Detection",
    "detect_seq_scan_on_large_table",
    "detect_like_leading_wildcard",
    "detect_function_in_where",
    "detect_or_across_tables",
    "detect_correlated_subquery",
    "Recommendation",
    "recommend_for_seq_scan_on_large_table",
]
