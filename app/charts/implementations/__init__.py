from app.charts.implementations.kpi import KPIImplementation
from app.charts.implementations.line import LineImplementation

charts_implementations = [
    KPIImplementation,
    LineImplementation
]

__all__ = [
    "KPIImplementation",
    "LineImplementation",

    "charts_implementations"
]
