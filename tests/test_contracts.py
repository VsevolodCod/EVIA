import copy
import json

from jsonschema import Draft202012Validator, FormatChecker
import pytest
from pydantic import ValidationError

from app.contracts.v1 import CONTRACTS, AgentResponse, Profile, QueryResult
from app.models import AskResponse
from scripts.export_contracts import ROOT, documents, serialized


@pytest.mark.parametrize('path,document', documents().items())
def test_export_is_current_and_fixtures_validate(path, document):
    assert (ROOT / path).read_text(encoding='utf-8') == serialized(document), 'Run python -m scripts.export_contracts'
    if path.startswith('fixtures/'):
        schema = json.loads((ROOT / f"{document['contract']}.schema.json").read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document['data'])
        CONTRACTS[document['contract']].model_validate(document['data'])


def test_legacy_agent_reader_accepts_additive_contract():
    data = documents()['fixtures/success.json']['data']
    assert AskResponse.model_validate(data).answer == data['answer']


def full_profile_data():
    return {
        'sample_size': 5,
        'sample_limit': 500,
        'processed_rows': 12,
        'coverage': 'full',
        'snapshot_id': 'snapshot-001',
        'note': 'Top values use a bounded sample.',
        'columns': {
            'amount': {
                'sample_non_null_count': 5,
                'sample_null_count': 0,
                'distinct_sample_values': 4,
                'top_values': [{'value': '12.50', 'count': 2}],
                'top_values_coverage': 'sample',
                'non_null_count': 10,
                'null_count': 2,
                'empty_count': 1,
                'distinct_count': 8,
                'uniqueness_ratio': 0.8,
                'is_identifier_candidate': False,
                'numeric': {
                    'count': 10,
                    'minimum': '0.01',
                    'maximum': '100.50',
                    'total': '457.75',
                    'average': '45.775',
                },
            },
            'created_at': {
                'sample_non_null_count': 5,
                'sample_null_count': 0,
                'distinct_sample_values': 5,
                'top_values': [],
                'top_values_coverage': 'sample',
                'non_null_count': 12,
                'null_count': 0,
                'empty_count': 0,
                'distinct_count': 12,
                'uniqueness_ratio': 1.0,
                'is_identifier_candidate': True,
                'temporal': {
                    'count': 12,
                    'minimum': '2026-01-01T00:00:00Z',
                    'maximum': '2026-01-12T00:00:00Z',
                },
            },
        },
    }


def test_profile_distinguishes_exact_snapshot_statistics_from_sample_top_values():
    profile = Profile.model_validate(full_profile_data()).root

    assert profile.processed_rows == 12
    assert profile.coverage == 'full'
    assert profile.snapshot_id == 'snapshot-001'
    assert profile.columns['amount'].numeric.minimum == '0.01'
    assert profile.columns['amount'].top_values_coverage == 'sample'
    assert profile.columns['created_at'].temporal.maximum == '2026-01-12T00:00:00Z'


@pytest.mark.parametrize('path', [
    ('processed_rows',),
    ('snapshot_id',),
    ('columns', 'amount', 'non_null_count'),
    ('columns', 'amount', 'null_count'),
    ('columns', 'amount', 'empty_count'),
    ('columns', 'amount', 'distinct_count'),
    ('columns', 'amount', 'uniqueness_ratio'),
    ('columns', 'amount', 'is_identifier_candidate'),
    ('columns', 'amount', 'top_values_coverage'),
])
def test_full_profile_rejects_missing_or_null_exact_statistics(path):
    for invalid_value in (None, ...):
        data = copy.deepcopy(full_profile_data())
        target = data
        for key in path[:-1]:
            target = target[key]
        if invalid_value is ...:
            target.pop(path[-1])
        else:
            target[path[-1]] = invalid_value
        with pytest.raises(ValidationError):
            Profile.model_validate(data)


def test_profile_without_explicit_coverage_is_rejected():
    data = full_profile_data()
    data.pop('coverage')
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_profile_accepts_bounded_sample_without_exact_snapshot_claims():
    profile = Profile.model_validate({
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
    })

    assert profile.root.coverage == 'sample'
    assert profile.model_dump() == {
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


def test_sample_profile_rejects_dataset_wide_statistics():
    data = {
        'sample_size': 2,
        'sample_limit': 100,
        'coverage': 'sample',
        'note': 'Column statistics use a bounded sample.',
        'columns': {
            'id': {
                'sample_non_null_count': 2,
                'sample_null_count': 0,
                'distinct_sample_values': 2,
                'top_values': [],
                'distinct_count': 2,
            },
        },
    }
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


@pytest.mark.parametrize('mutation', ['width', 'limit', 'count', 'decimal'])
def test_inconsistent_table_rejected(mutation):
    query = copy.deepcopy(documents()['fixtures/query.json']['data'])
    if mutation == 'width': query['rows'][0].append('extra')
    if mutation == 'limit': query['row_limit'] = 0
    if mutation == 'count': query['returned_rows'] = 2
    if mutation == 'decimal': query['rows'][0][0] = 30.5
    with pytest.raises(ValidationError): QueryResult.model_validate(query)


def test_clarification_cannot_claim_computed_results():
    data = documents()['fixtures/success.json']['data']
    data['status'] = 'clarification'
    with pytest.raises(ValidationError): AgentResponse.model_validate(data)
