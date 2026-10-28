from app.charts.implementations.line import LineImplementation
from app.charts.models import BarCard, ChartDefinition


class BarImplementation(LineImplementation):
    """Grouped bars share the line chart's validated aggregation contract."""

    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, BarCard)
