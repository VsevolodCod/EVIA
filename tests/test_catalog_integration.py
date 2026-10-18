"""Compatibility of the merged SQLAlchemy catalog and workspace settings."""

import sqlite3

from app.config import Settings
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


def test_catalog_initializes_clean_database_and_survives_reopen(tmp_path):
    path = tmp_path / 'nested' / 'catalog.db'
    catalog = SchemaCatalog(path)
    assert catalog.list_sources() == []
    source = SourceService(tmp_path / 'csv', catalog).register_csv(
        filename='synthetic.csv', content=b'id,value\n0001,7\n')
    catalog.close()
    reopened = SchemaCatalog(path)
    try:
        assert reopened.get_source(source.source_id) == source
        assert reopened.get_schema(source.source_id).objects[0].row_count == 1
    finally:
        reopened.close()


def test_catalog_keeps_legacy_sqlite_tables_usable(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE sources(source_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE schemas(source_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
    catalog = SchemaCatalog(path)
    try:
        service = SourceService(tmp_path / 'csv', catalog)
        source = service.register_csv(filename='synthetic.csv', content=b'id\n0001\n')
        assert service.preview(source.source_id, 1) == [{'id': '0001'}]
    finally:
        catalog.close()


def test_settings_accept_old_catalog_name_and_prefer_new_one(tmp_path, monkeypatch):
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('CATALOG_DB_PATH', raising=False)
    monkeypatch.delenv('CHAT_DB_PATH', raising=False)
    monkeypatch.setenv('BI_CATALOG_DB', str(tmp_path / 'old.db'))
    assert Settings().catalog_db_path == tmp_path / 'old.db'
    assert Settings().chat_db_path == tmp_path / 'chats.db'
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'new.db'))
    assert Settings().catalog_db_path == tmp_path / 'new.db'
