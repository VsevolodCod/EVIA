from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CatalogBase


class DataSourceORM(CatalogBase):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
    )
    # NULL для CSV; задан для таблиц PostgreSQL.
    connection_id: Mapped[str | None] = mapped_column(
        String(200),
        ForeignKey("connections.connection_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
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


class ConnectionORM(CatalogBase):
    __tablename__ = "connections"

    connection_id: Mapped[str] = mapped_column(
        String(200),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connection_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )