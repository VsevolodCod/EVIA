from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ChatBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChatORM(ChatBase):
    __tablename__ = "chats"

    chat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # No foreign key: archived analyses remain readable after source removal.
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="Новый чат",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    messages: Mapped[list["ChatMessageORM"]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="ChatMessageORM.position",
        lazy="selectin",
    )


class ChatMessageORM(ChatBase):
    __tablename__ = "chat_messages"

    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "position",
            name="uq_chat_messages_position",
        ),
        Index("ix_chat_messages_chat_position", "chat_id", "position"),
    )

    message_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.chat_id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    tool_calls: Mapped[list[dict] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_payload: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    chat: Mapped["ChatORM"] = relationship(back_populates="messages")
