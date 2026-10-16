from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CatalogBase


class DataSourceORM(CatalogBase):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)


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