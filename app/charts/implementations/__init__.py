from app.charts.implementations.kpi import KPIImplementation
from app.charts.implementations.line import LineImplementation
from app.charts.implementations.bar import BarImplementation
from app.charts.implementations.pie import PieImplementation
from app.charts.implementations.scatter import ScatterImplementation
from app.charts.implementations.table import TableImplementation

charts_implementations = [
    KPIImplementation,
    LineImplementation,
    BarImplementation,
    PieImplementation,
    ScatterImplementation,
    TableImplementation,
]

__all__ = [
    "KPIImplementation",
    "LineImplementation",
    "BarImplementation",
    "PieImplementation",
    "ScatterImplementation",
    "TableImplementation",

    "charts_implementations"
]
