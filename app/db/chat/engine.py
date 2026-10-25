from pathlib import Path

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import ChatBase


def create_chat_database(
    db_path: Path,
) -> tuple[AsyncEngine, async_sessionmaker]:
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = URL.create(
        "sqlite+aiosqlite",
        database=str(db_path),
    )

    engine = create_async_engine(url)

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    return engine, session_factory


async def initialize_chat_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(ChatBase.metadata.create_all)
        columns = await connection.exec_driver_sql("PRAGMA table_info(chat_messages)")
        if "response" not in {row[1] for row in columns}:
            await connection.exec_driver_sql("ALTER TABLE chat_messages ADD COLUMN response JSON")
