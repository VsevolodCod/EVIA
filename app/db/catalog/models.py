from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CatalogBase


class DataSourceORM(CatalogBase):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class SourceSchemaORM(CatalogBase):
    __tablename__ = "schemas"

    source_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class DashboardORM(CatalogBase):
    """Сохранённый дашборд; chart_refs упорядочены по position."""

    __tablename__ = "dashboards"

    dashboard_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    chart_refs: Mapped[list["DashboardChartRefORM"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardChartRefORM.position",
        lazy="selectin",
    )


class ChartORM(CatalogBase):
    """Сохранённое определение чарта."""

    __tablename__ = "charts"

    chart_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class DashboardChartRefORM(CatalogBase):
    """Связь дашборда с чартом и позиция чарта в дашборде."""

    __tablename__ = "chart_refs"

    dashboard_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("dashboards.dashboard_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chart_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("charts.chart_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    dashboard: Mapped["DashboardORM"] = relationship(
        back_populates="chart_refs",
    )
    chart: Mapped["ChartORM"] = relationship(
        lazy="joined",
    )
