import pytest
from httpx import ASGITransport, AsyncClient

from app.models import DataSource
from app.ownership import current_owner
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


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
