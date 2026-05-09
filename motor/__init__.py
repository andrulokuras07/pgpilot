"""API pública del módulo `motor`.

Hoy: parser de EXPLAIN (B7+B8) y helper de búsqueda en el árbol (B9).
A medida que se agreguen detectores y recomendador, se exportan
desde aquí.
"""

from motor.nodes import KNOWN_NODE_TYPES, find_nodes
from motor.parser import ExplainResult, PlanNode, parse_explain

__all__ = [
    "ExplainResult",
    "PlanNode",
    "parse_explain",
    "find_nodes",
    "KNOWN_NODE_TYPES",
]
