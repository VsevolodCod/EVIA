from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from app.profile_cache import ProfileCache
from app.models import DataSource
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


def test_cached_profiles_are_detached_and_lru_is_bounded():
    cache = ProfileCache(max_entries=2)
    calls = []

    def get(key):
        def compute():
            calls.append(key)
            return {'columns': {'id': {'top_values': ['001']}}}
        return cache.get_or_compute((key,), compute)

    get('a')['columns']['id']['top_values'][0] = 'changed'
    assert get('a')['columns']['id']['top_values'] == ['001']
    get('b')
    get('a')
    get('c')  # b is least recently used.
    get('a')
    get('b')
    assert calls == ['a', 'b', 'c', 'b']


def test_cache_has_byte_budget_and_does_not_keep_oversized_results():
    cache = ProfileCache(max_entries=10, max_bytes=12)
    calls = []

    def get(key, value):
        def compute():
            calls.append(key)
            return {'x': value}
        return cache.get_or_compute((key,), compute)

    get('a', 1)
    get('b', 2)  # Each encoded value fits, both together do not.
    get('a', 1)
    get('large', 'x' * 30)
    get('large', 'x' * 30)
    get('a', 1)  # Oversized values must not evict the useful entry.
    assert calls == ['a', 'b', 'a', 'large', 'large']


def test_concurrent_readers_share_work_without_serializing_other_keys():
    cache = ProfileCache()
    started, release = Event(), Event()
    calls = []

    def compute():
        calls.append('same')
        started.set()
        assert release.wait(5), 'test failed to release the computation'
        return {'nested': [1]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.get_or_compute, ('same',), compute)
        try:
            assert started.wait(5)
            second = pool.submit(cache.get_or_compute, ('same',), compute)
            other = pool.submit(cache.get_or_compute, ('other',), lambda: {'x': 2})
            assert other.result(timeout=5) == {'x': 2}
        finally:
            release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    a['nested'][0] = 99
    assert b == {'nested': [1]}
    assert calls == ['same']


def test_failed_computation_can_be_retried():
    cache = ProfileCache()

    def fail():
        raise ValueError('not a valid profile')

    with pytest.raises(ValueError, match='not a valid profile'):
        cache.get_or_compute(('snapshot',), fail)
    assert cache.get_or_compute(('snapshot',), lambda: {'ok': True}) == {'ok': True}


@pytest.fixture
def source_setup(tmp_path, monkeypatch):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    sources = SourceService(tmp_path / 'data', catalog)
    source = sources.register_csv('data.csv', b'id,date,amount\n001,2024-01-01,10\n002,2024-01-03,20\n')
    original = sources.data_engine.profile
    calls = []

    def counted(source, sample_size):
        calls.append((source.source_id, source.snapshot_id, source.schema_version, sample_size))
        return original(source, sample_size)

    monkeypatch.setattr(sources.data_engine, 'profile', counted)
    yield sources, source, catalog, calls
    catalog.close()


def test_profile_reuse_and_reimport_do_not_mix_versions(source_setup):
    sources, source, _, calls = source_setup
    old = sources.profile(source.source_id)
    old['columns']['id']['top_values'].clear()
    assert sources.profile(source.source_id)['columns']['id']['top_values']
    assert len(calls) == 1
    replacement = sources.register_csv('new.csv', b'id,date,amount\n003,2026-01-01,30\n', source_id=source.source_id)
    new = sources.profile(source.source_id)
    assert new['snapshot_id'] == replacement.snapshot_id != old['snapshot_id']
    assert new['processed_rows'] == 1
    assert new['columns']['date']['temporal']['minimum'].startswith('2026-01-01')
    assert sources.profile(source.source_id) == new
    assert len(calls) == 2


def test_live_postgresql_profiles_are_never_cached(source_setup):
    sources, _, catalog, _ = source_setup
    live = DataSource(source_id='live', name='live', source_type='postgresql')
    catalog.upsert_source(live)
    calls = []

    def profile(source):
        calls.append(source.source_id)
        return {'coverage': 'sample', 'sample_size': 0, 'sample_limit': 500,
                'columns': {}, 'note': f'live read {len(calls)}'}

    sources.postgres_adapter = SimpleNamespace(profile=profile)
    assert sources.profile(live.source_id)['note'] == 'live read 1'
    assert sources.profile(live.source_id)['note'] == 'live read 2'
    assert calls == ['live', 'live']


def test_profile_cache_separates_sources_schema_versions_and_sample_limits(source_setup):
    sources, source, catalog, calls = source_setup
    sources.profile(source.source_id)
    sources.csv_adapter.sample_size = 1
    limited = sources.profile(source.source_id)
    assert limited['sample_size'] == limited['sample_limit'] == 1
    assert limited['processed_rows'] == 2
    refreshed = catalog.get_source(source.source_id)
    refreshed.schema_version += 1
    catalog.upsert_source(refreshed)
    sources.profile(source.source_id)
    other = sources.register_csv('other.csv', b'name\nother\n')
    assert sources.profile(other.source_id)['processed_rows'] == 1
    assert len(calls) == 4


def test_failed_reimport_does_not_discard_valid_profile(source_setup):
    sources, source, _, calls = source_setup
    before = sources.profile(source.source_id)
    with pytest.raises(ValueError):
        sources.register_csv('invalid.csv', b'', source_id=source.source_id)
    assert sources.profile(source.source_id) == before
    assert len(calls) == 1


def test_invalid_profile_is_not_published_or_cached(source_setup, monkeypatch):
    sources, source, _, calls = source_setup
    original = sources.data_engine.profile

    def invalid(source, sample_size):
        profile = original(source, sample_size)
        profile['snapshot_id'] = 'another-snapshot'
        return profile

    monkeypatch.setattr(sources.data_engine, 'profile', invalid)
    with pytest.raises(ValueError, match='requested CSV snapshot'):
        sources.profile(source.source_id)
    monkeypatch.setattr(sources.data_engine, 'profile', original)
    assert sources.profile(source.source_id)['snapshot_id'] == source.snapshot_id
    assert len(calls) == 2
