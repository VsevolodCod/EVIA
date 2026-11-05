"""Request-scoped account identity for the existing persistence services."""

from contextvars import ContextVar


current_owner: ContextVar[str | None] = ContextVar("evia_owner", default=None)


def owner_id() -> str | None:
    return current_owner.get()
