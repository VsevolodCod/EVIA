from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.db.catalog.models import DataSourceORM, SourceSchemaORM
from app.db.base import CatalogBase
from app.models import DataSource, SourceSchema


class SchemaCatalog:
    def __init__(
        self,
        db_path: Path,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._engine = None

        if session_factory is None:
            url = URL.create(
                "sqlite+pysqlite",
                database=str(self.db_path),
            )
            self._engine = create_engine(url)
            CatalogBase.metadata.create_all(self._engine)
            self.session_factory = sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )
        else:
            self.session_factory = session_factory

    def upsert_source(self, source: DataSource) -> None:
        with self.session_factory.begin() as session:
            record = session.get(DataSourceORM, source.source_id)

            if record is None:
                record = DataSourceORM(
                    source_id=source.source_id,
                    payload=source.model_dump_json(),
                )
                session.add(record)
            else:
                record.payload = source.model_dump_json()

    def save_source_and_schema(self, source: DataSource, schema: SourceSchema) -> None:
        """Publish a CSV snapshot and its schema in one catalog transaction."""
        with self.session_factory.begin() as session:
            record = session.get(DataSourceORM, source.source_id)
            if record is None:
                session.add(DataSourceORM(source_id=source.source_id, payload=source.model_dump_json()))
            else:
                record.payload = source.model_dump_json()
            schema_record = session.get(SourceSchemaORM, schema.source_id)
            if schema_record is None:
                session.add(SourceSchemaORM(source_id=schema.source_id, version=schema.version,
                                            payload=schema.model_dump_json()))
            else:
                schema_record.version = schema.version
                schema_record.payload = schema.model_dump_json()

    def get_source(self, source_id: str) -> DataSource | None:
        with self.session_factory() as session:
            record = session.get(DataSourceORM, source_id)

            if record is None:
                return None

            payload = record.payload

        return DataSource.model_validate_json(payload)

    def list_sources(self) -> list[DataSource]:
        with self.session_factory() as session:
            records = session.scalars(
                select(DataSourceORM).order_by(DataSourceORM.source_id)
            ).all()

            payloads = [record.payload for record in records]

        return [
            DataSource.model_validate_json(payload)
            for payload in payloads
        ]

    def save_schema(self, schema: SourceSchema) -> None:
        with self.session_factory.begin() as session:
            record = session.get(SourceSchemaORM, schema.source_id)

            if record is None:
                record = SourceSchemaORM(
                    source_id=schema.source_id,
                    version=schema.version,
                    payload=schema.model_dump_json(),
                )
                session.add(record)
            else:
                record.version = schema.version
                record.payload = schema.model_dump_json()

    def get_schema(self, source_id: str) -> SourceSchema | None:
        with self.session_factory() as session:
            record = session.get(SourceSchemaORM, source_id)

            if record is None:
                return None

            payload = record.payload

        return SourceSchema.model_validate_json(payload)

    def close(self) -> None:
        """Освободить ресурсы движка, если он создан этим объектом."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
