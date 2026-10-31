import pytest
import duckdb
from httpx import ASGITransport, AsyncClient
from pathlib import Path

from app.models import DataSource
from app.ownership import current_owner
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.data_engine import DuckDBDataEngine


def test_delete_csv_removes_all_versions_and_keeps_other_source(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    first = service.register_csv('one.csv', b'value\n1\n')
    second = service.register_csv('one.csv', b'value\n2\n', source_id=first.source_id)
    other = service.register_csv('two.csv', b'value\n3\n')
    versions = [first, second]
    paths = [service.data_dir / filename for version in second.csv_versions
             for filename in (version.raw_filename, version.normalized_filename)]
    assert all(path.exists() for path in paths)
    service.delete_csv(first.source_id)
    assert catalog.get_source(first.source_id) is None
    assert catalog.get_schema(first.source_id) is None
    assert not any(path.exists() for path in paths)
    assert all(not service.data_engine.has_table(version) for version in versions)
    assert service.data_engine.has_table(other)
    assert service.preview(other.source_id) == [{'value': '3'}]


def test_delete_refuses_another_users_source_and_postgresql(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    token = current_owner.set('owner-a')
    try:
        source = service.register_csv('one.csv', b'value\n1\n')
        postgres = DataSource(source_id='pg', name='postgres', source_type='postgresql')
        catalog.upsert_source(postgres)
    finally:
        current_owner.reset(token)
    token = current_owner.set('owner-b')
    try:
        with pytest.raises(KeyError):
            service.delete_csv(source.source_id)
    finally:
        current_owner.reset(token)
    token = current_owner.set('owner-a')
    try:
        with pytest.raises(ValueError):
            service.delete_csv(postgres.source_id)
        assert catalog.get_source(source.source_id)
        assert service.preview(source.source_id) == [{'value': '1'}]
    finally:
        current_owner.reset(token)


@pytest.mark.asyncio
async def test_delete_endpoint_removes_csv_and_returns_404_for_missing(tmp_path, monkeypatch):
    import app.main as main
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    source = service.register_csv('one.csv', b'value\n1\n')
    monkeypatch.setattr(main, 'source_service', service)
    monkeypatch.setattr(main.settings, 'auth_enabled', False)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete(f'/sources/{source.source_id}')
        assert response.status_code == 200
        assert response.json() == {'success': True}
        assert (await client.delete(f'/sources/{source.source_id}')).status_code == 404
    assert catalog.get_source(source.source_id) is None


def test_failed_delete_is_not_served_and_can_be_retried(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    source = service.register_csv('one.csv', b'value\n1\n')
    real_unlink = Path.unlink
    def fail_once(path, *args, **kwargs):
        if path.name == source.csv_versions[0].raw_filename:
            raise OSError('injected failure')
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_once)
    with pytest.raises(OSError):
        service.delete_csv(source.source_id)
    assert catalog.get_source(source.source_id) is None
    assert catalog.get_source(source.source_id, include_deleting=True).status == 'deleting'
    with pytest.raises(ValueError):
        service.register_csv('one.csv', b'value\n2\n', source_id=source.source_id)
    monkeypatch.setattr(Path, 'unlink', real_unlink)
    service.delete_csv(source.source_id)
    assert catalog.get_source(source.source_id, include_deleting=True) is None


def test_compaction_reclaims_disk_and_preserves_remaining_tables(tmp_path):
    db = tmp_path / 'analytics.duckdb'
    with duckdb.connect(str(db)) as connection:
        connection.execute("create table removed as select i, md5(i::VARCHAR) as text_value from range(300000) t(i)")
        connection.execute("CHECKPOINT")
        connection.execute("create table retained as select i, md5(i::VARCHAR) as text_value from range(10000) t(i)")
        connection.execute("CHECKPOINT")
        connection.execute("drop table removed")
        connection.execute("CHECKPOINT")
    before = db.stat().st_size
    DuckDBDataEngine(db).compact()
    assert db.stat().st_size < before
    with duckdb.connect(str(db), read_only=True) as connection:
        assert connection.execute('select count(*), min(i), max(i) from retained').fetchone() == (10000, 0, 9999)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["discard", "compact"])
async def test_delete_endpoint_explains_when_disk_is_too_full_to_compact(tmp_path, monkeypatch, operation):
    import errno
    import app.main as main
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    source = service.register_csv('one.csv', b'value\n1\n')
    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, 'disk full')
    monkeypatch.setattr(service.data_engine, operation, no_space)
    monkeypatch.setattr(main, 'source_service', service)
    monkeypatch.setattr(main.settings, 'auth_enabled', False)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.delete(f'/sources/{source.source_id}')
    assert response.status_code == 507
    assert 'повторите удаление' in response.json()['detail'].lower()
    assert catalog.get_source(source.source_id, include_deleting=True).status == 'deleting'
