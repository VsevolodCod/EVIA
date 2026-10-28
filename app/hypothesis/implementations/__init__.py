from app.hypothesis.implementations.compare import CompareImplementation
from app.hypothesis.implementations.relationship import (
    RelationshipImplementation,
)

hypothesis_implementations = [
    CompareImplementation,
    RelationshipImplementation,
]

__all__ = [
    "CompareImplementation",
    "RelationshipImplementation",
    
    "hypothesis_implementations",
]
