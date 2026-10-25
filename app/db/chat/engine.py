from pathlib import Path

from sqlalchemy import text
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
        # Serialize schema inspection/ALTER across simultaneous process starts.
        await connection.execute(text('BEGIN IMMEDIATE'))
        await connection.run_sync(ChatBase.metadata.create_all)
        for table, column, definition in (
            ('chats', 'source_id', 'VARCHAR(200)'),
            ('chat_messages', 'analysis_payload', 'JSON'),
            ('chat_messages', 'response', 'JSON'),
        ):
            columns = await connection.execute(text(f'PRAGMA table_info({table})'))
            if column not in {row[1] for row in columns}:
                await connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
