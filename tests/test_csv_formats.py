import hashlib

import pytest

from app.models import SourceSchema
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.data_sources.csv_format import PARSER_VERSION


@pytest.fixture
def service(tmp_path):
    catalog = SchemaCatalog(tmp_path / 'catalog.db')
    try:
        yield SourceService(tmp_path / 'csv', catalog)
    finally:
        catalog.close()


@pytest.mark.parametrize('separator', [',', ';', '\t', '|'])
@pytest.mark.parametrize('line_ending', ['\n', '\r\n', '\r'])
def test_dialect_is_shared_and_original_values_preserved(service, separator, line_ending):
    import csv
    import io
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=separator, lineterminator=line_ending)
    writer.writerow(['Код позиции', 'Цена, руб.', 'Комментарий'])
    writer.writerow(['0001', '-123,45', 'Первая строка\nВторая; "цитата"'])
    writer.writerow(['0002', '0,00', ''])
    content = ('\ufeff' + output.getvalue()).encode('utf-8')
    source = service.register_csv('synthetic.csv', content)
    schema = service.get_schema(source.source_id)
    assert schema.objects[0].row_count == 2
    assert len(schema.objects[0].fields) == 3
    assert schema.objects[0].fields[0].inferred_type == 'string'
    assert schema.objects[0].fields[1].inferred_type == 'number'
    rows = service.preview(source.source_id)
    assert rows[0] == {'Код позиции': '0001', 'Цена, руб.': '-123,45', 'Комментарий': 'Первая строка\nВторая; "цитата"'}
    assert service.profile(source.source_id)['columns']['Цена, руб.']['sample_non_null_count'] == 2
    assert hashlib.sha256((service.data_dir / f'{source.source_id}.csv').read_bytes()).digest() == hashlib.sha256(content).digest()


@pytest.mark.parametrize('content', [b'id;id\n1;2\n', b'id;value\n1;2;3\n', b'id;value\n1\n', b'id;value\n1;"unterminated'])
def test_invalid_csv_does_not_register_partial_source(service, content):
    with pytest.raises(ValueError):
        service.register_csv('invalid.csv', content)
    assert service.catalog.list_sources() == []
    assert list(service.data_dir.glob('*.csv')) == []


def test_full_file_validation_catches_wrong_width_after_sample(service):
    content = b'id;value\n' + b'0001;2\n' * 501 + b'0002;3;extra\n'
    with pytest.raises(ValueError, match='fields'):
        service.register_csv('tail.csv', content)


@pytest.mark.parametrize('old_parser_version', [1, 2])
def test_legacy_schema_repaired_once_without_reupload(service, old_parser_version):
    source = service.register_csv('synthetic.csv', b'id;value\n001;10\n')
    service.catalog.save_schema(SourceSchema(source_id=source.source_id, parser_version=old_parser_version))
    original = (service.data_dir / f'{source.source_id}.csv').read_bytes()
    repaired = service.get_schema(source.source_id)
    assert repaired.parser_version == PARSER_VERSION
    assert repaired.version == 2
    assert [f.name for f in repaired.objects[0].fields] == ['id', 'value']
    assert service.get_schema(source.source_id).version == 2
    assert (service.data_dir / f'{source.source_id}.csv').read_bytes() == original
