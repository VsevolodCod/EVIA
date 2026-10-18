import copy
import json

from jsonschema import Draft202012Validator, FormatChecker
import pytest
from pydantic import ValidationError

from app.contracts.v1 import CONTRACTS, AgentResponse, QueryResult
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
