"""Contract exercised by the workspace, against the real FastAPI and CSV service."""

import importlib

from httpx import ASGITransport, AsyncClient
import pytest

from app.contracts.v1 import Profile
from app.data_sources.postgresql_adapter import PostgresSourceError


@pytest.mark.asyncio
async def test_workspace_csv_to_agent_contract(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'mock')
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.sqlite3'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'chats.sqlite3'))
    module = importlib.import_module('app.main')
    route = next(route for route in module.app.routes if route.path == '/sources/{source_id}/profile')
    assert route.response_model is Profile
    async with module.app.router.lifespan_context(module.app), AsyncClient(
        transport=ASGITransport(app=module.app, raise_app_exceptions=False), base_url='http://test'
    ) as client:
        assert (await client.get('/health')).json()['llm_provider'] == 'mock'
        assert (await client.get('/sources')).json() == []
        assert (await client.get('/chats')).json() == []
        empty = await client.post('/sources/csv', files={'file': ('empty.csv', b'', 'text/csv')})
        assert empty.status_code == 400
        upload = await client.post('/sources/csv', files={'file': ('sales.csv', b'id,revenue\n001,10\n002,20\n', 'text/csv')})
        assert upload.status_code == 200
        source_id = upload.json()['source_id']
        assert (await client.get('/sources')).json()[0]['source_id'] == source_id
        schema = (await client.get(f'/sources/{source_id}/schema')).json()
        assert schema['objects'][0]['row_count'] == 2
        assert schema['objects'][0]['fields'][0]['inferred_type'] == 'string'
        preview = (await client.get(f'/sources/{source_id}/preview?limit=100')).json()
        assert preview == [{'id': '001', 'revenue': '10'}, {'id': '002', 'revenue': '20'}]
        profile = (await client.get(f'/sources/{source_id}/profile')).json()
        Profile.model_validate(profile)
        assert profile['coverage'] == 'full'
        assert profile['snapshot_id'] == upload.json()['snapshot_id']
        assert profile['sample_size'] == 2
        assert profile['columns']['id']['sample_null_count'] == 0
        result = await client.post('/agent/ask', json={'question': 'Что есть в данных?', 'source_ids': [source_id]})
        assert result.status_code == 200
        answer = result.json()
        assert answer['answer']
        assert answer['tool_results'][0]['tool_name'] == 'preview_data'
        assert answer['tool_results'][0]['ok']
        assert answer['tool_results'][0]['data'][0] == {'id': '001', 'revenue': '10'}
        assert (await client.get('/chats')).json() == [], 'Stateless UI questions must not create persistent chats'
        assert (await client.post('/agent/ask', json={'question': '', 'source_ids': [source_id]})).status_code == 422
        assert (await client.get('/sources/missing/schema')).status_code == 404
        assert (await client.get('/sources/missing/profile')).status_code == 404
        monkeypatch.setattr(module.source_service, 'profile', lambda _source_id: {'coverage': 'full'})
        assert (await client.get(f'/sources/{source_id}/profile')).status_code == 500


@pytest.mark.asyncio
async def test_profile_api_validates_sampled_postgresql_profiles_and_maps_source_errors(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'mock')
    monkeypatch.setenv('BI_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.sqlite3'))
    monkeypatch.setenv('CHAT_DB_PATH', str(tmp_path / 'chats.sqlite3'))
    module = importlib.import_module('app.main')
    sampled_profile = {
        'sample_size': 2,
        'sample_limit': 100,
        'coverage': 'sample',
        'note': 'Column statistics use a bounded sample.',
        'columns': {
            'id': {
                'sample_non_null_count': 2,
                'sample_null_count': 0,
                'distinct_sample_values': 2,
                'top_values': [{'value': '1', 'count': 1}],
            },
        },
    }
    async with module.app.router.lifespan_context(module.app), AsyncClient(
        transport=ASGITransport(app=module.app, raise_app_exceptions=False), base_url='http://test'
    ) as client:
        monkeypatch.setattr(module.source_service, 'profile', lambda _source_id: sampled_profile)
        response = await client.get('/sources/postgresql:public:orders/profile')
        assert response.status_code == 200
        assert response.json() == sampled_profile
        Profile.model_validate(response.json())

        monkeypatch.setattr(module.source_service, 'profile', lambda _source_id: {
            **sampled_profile, 'processed_rows': 2,
        })
        assert (await client.get('/sources/postgresql:public:orders/profile')).status_code == 500

        def unavailable(_source_id):
            raise PostgresSourceError('CONNECTION_FAILED')

        monkeypatch.setattr(module.source_service, 'profile', unavailable)
        unavailable_response = await client.get('/sources/postgresql:public:orders/profile')
        assert unavailable_response.status_code == 503
        assert unavailable_response.json() == {'detail': {
            'code': 'CONNECTION_FAILED',
            'message': 'PostgreSQL source is temporarily unavailable.',
            'retryable': True,
        }}

        def timed_out(_source_id):
            raise PostgresSourceError('QUERY_TIMEOUT')

        monkeypatch.setattr(module.source_service, 'profile', timed_out)
        timeout_response = await client.get('/sources/postgresql:public:orders/profile')
        assert timeout_response.status_code == 504
        assert timeout_response.json()['detail']['code'] == 'QUERY_TIMEOUT'
