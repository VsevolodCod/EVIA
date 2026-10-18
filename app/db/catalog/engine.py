from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import CatalogBase

# Импортируем ORM-модели, чтобы они зарегистрировались
# в CatalogBase.metadata перед create_all.
# from app.db.catalog import (
#     ConnectionORM,
#     DataSourceORM,
#     SourceSchemaORM,
# )


def create_catalog_database(
    db_path: Path,
) -> tuple[Engine, sessionmaker[Session]]:
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = URL.create(
        "sqlite+pysqlite",
        database=str(db_path),
    )

    engine = create_engine(url)

    CatalogBase.metadata.create_all(engine)

    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return engine, session_factory
