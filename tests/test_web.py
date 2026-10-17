from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web import mount_frontend


def make_app(directory: Path):
    app = FastAPI()

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    mount_frontend(app, directory)
    return app


@pytest.mark.asyncio
async def test_missing_build_keeps_api_usable(tmp_path):
    client = AsyncClient(transport=ASGITransport(app=make_app(tmp_path / 'missing')), base_url='http://test')
    assert (await client.get('/health')).json() == {'status': 'ok'}
    assert (await client.get('/')).status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_serves_bundle_without_shadowing_api(tmp_path):
    (tmp_path / 'index.html').write_text('<main>Линза BI</main>', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('window.testBundle = true;')
    client = AsyncClient(transport=ASGITransport(app=make_app(tmp_path)), base_url='http://test')
    assert 'Линза BI' in (await client.get('/')).text
    assert 'text/html' in (await client.get('/')).headers['content-type']
    assert (await client.get('/assets/app.js')).status_code == 200
    assert (await client.get('/health')).json() == {'status': 'ok'}
    assert (await client.get('/openapi.json')).status_code == 200
    assert (await client.get('/unknown.js')).status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_paths_outside_bundle_are_not_served(tmp_path):
    bundle = tmp_path / 'dist'
    bundle.mkdir()
    (bundle / 'index.html').write_text('<main>App</main>')
    secret = tmp_path / 'private.txt'
    secret.write_text('private sentinel')
    client = AsyncClient(transport=ASGITransport(app=make_app(bundle)), base_url='http://test')
    for path in ['/../private.txt', '/%2e%2e/private.txt']:
        response = (await client.get(path))
        assert response.status_code == 404
        assert 'private sentinel' not in response.text

    await client.aclose()


@pytest.mark.asyncio
async def test_symlinks_outside_bundle_are_not_served(tmp_path):
    bundle = tmp_path / 'dist'
    bundle.mkdir()
    (bundle / 'index.html').write_text('App', encoding='utf-8')
    secret = tmp_path / 'private.txt'
    secret.write_text('private sentinel', encoding='utf-8')
    try:
        (bundle / 'link.txt').symlink_to(secret)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows requires Developer Mode or symlink privilege')
        raise
    async with AsyncClient(transport=ASGITransport(app=make_app(bundle)), base_url='http://test') as client:
        response = await client.get('/link.txt')
        assert response.status_code == 404
        assert 'private sentinel' not in response.text
