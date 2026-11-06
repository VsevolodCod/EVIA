"""Small isolated concurrency smoke test, not a production load benchmark."""

import asyncio
import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


@pytest.mark.asyncio
async def test_concurrent_previews_remain_bounded_and_do_not_mix_sources(tmp_path, monkeypatch):
    module = importlib.import_module('app.main')
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    service = SourceService(tmp_path / 'data', catalog)
    monkeypatch.setattr(module, 'catalog', catalog)
    monkeypatch.setattr(module, 'source_service', service)
    monkeypatch.setattr(module.settings, 'auth_enabled', False)
    first = service.register_csv('first.csv', b'value\nfirst\nsecond\n')
    second = service.register_csv('second.csv', b'value\nprivate\nother\n')
    try:
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url='http://test') as client:
            # Twelve simultaneous requests per wave, three waves, in-process ASGI.
            for _ in range(3):
                paths = [f'/sources/{source.source_id}/preview?limit=1'
                         for source in (first, second) for _ in range(6)]
                responses = await asyncio.gather(*(client.get(path) for path in paths))
                assert all(response.status_code == 200 for response in responses)
                assert all(response.json() == [{'value': 'first'}] for response in responses[:6])
                assert all(response.json() == [{'value': 'private'}] for response in responses[6:])
    finally:
        catalog.close()
