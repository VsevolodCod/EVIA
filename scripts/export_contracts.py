"""Deterministic schema and synthetic fixture generation: python -m scripts.export_contracts."""
import json
from pathlib import Path

from app.contracts.v1 import CONTRACTS

ROOT = Path(__file__).resolve().parents[1] / 'contracts' / 'v1'


def documents():
    result = {}
    for name, model in CONTRACTS.items():
        result[f'{name}.schema.json'] = {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': f'urn:evia:contracts:1.0:{name}', **model.model_json_schema()}
    timestamp = '2026-10-17T00:00:00Z'
    source = {'source_id': 'synthetic-sales', 'name': 'Synthetic sales', 'source_type': 'csv',
              'status': 'available', 'created_at': timestamp, 'schema_version': 1}
    snapshot = {'source_id': source['source_id'], 'snapshot_id': 'snapshot-001', 'schema_version': 1,
                'content_sha256': '0' * 64, 'created_at': timestamp, 'state': 'ready', 'row_count': 2}
    query = {'result_id': 'result-001', 'columns': [{'name': 'amount', 'data_type': 'decimal', 'nullable': False}],
             'rows': [['30.50']], 'returned_rows': 1, 'row_limit': 100, 'truncated': False, 'elapsed_ms': 1.5,
             'provenance': [{'source_id': source['source_id'], 'snapshot_id': snapshot['snapshot_id'],
                             'schema_version': 1, 'tool_name': 'query_data', 'executed_at': timestamp}]}
    error = {'code': 'QUERY_TIMEOUT', 'message': 'Query time limit exceeded', 'request_id': 'request-error', 'retryable': True}
    fixtures = {
        'source': ('Source', source),
        'schema': ('SourceSchema', {'source_id': source['source_id'], 'parser_version': 2, 'version': 1, 'discovered_at': timestamp, 'objects': [], 'relations': []}),
        'snapshot': ('DatasetSnapshot', snapshot),
        'profile': ('Profile', {'sample_size': 2, 'sample_limit': 500, 'columns': {'id': {
            'sample_non_null_count': 2, 'sample_null_count': 0, 'distinct_sample_values': 2,
            'top_values': [{'value': '0001', 'count': 1}, {'value': '0002', 'count': 1}]}}, 'note': 'Bounded sample'}),
        'query': ('QueryResult', query),
        'empty': ('QueryResult', {**query, 'rows': [], 'returned_rows': 0}),
        'success': ('AgentResponse', {'answer': 'Synthetic fixture: 30.50', 'steps': 2,
            'tool_results': [{'tool_name': 'preview_data', 'ok': True, 'data': [{'id': '0001'}], 'error': None}],
            'request_id': 'request-success', 'status': 'answered', 'results': [query],
            'analysis': {'intent': 'sum', 'sql': 'SELECT SUM(amount) FROM synthetic_sales', 'explanation': 'Fixture only; SQL is not executed by this schema'}}),
        'clarification': ('AgentResponse', {'answer': 'Which period?', 'steps': 1, 'tool_results': [],
                                           'request_id': 'request-clarification', 'status': 'clarification'}),
        'failure': ('AgentResponse', {'answer': 'Query timed out', 'steps': 1, 'tool_results': [],
                                     'request_id': 'request-error', 'status': 'error', 'error': error}),
        'error': ('Error', error),
    }
    for name, (contract, data) in fixtures.items():
        validated = CONTRACTS[contract].model_validate(data).model_dump(mode='json')
        result[f'fixtures/{name}.json'] = {'contract': contract, 'data': validated}
    return result


def serialized(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


if __name__ == '__main__':
    for path, document in documents().items():
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized(document), encoding='utf-8')
    print(f'Exported {len(documents())} schemas/fixtures')
