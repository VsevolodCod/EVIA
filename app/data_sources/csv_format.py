"""One CSV dialect decision shared by validation, schema, preview and profile."""

import csv
import io
from itertools import islice
from typing import TextIO

PARSER_VERSION = 3
SAMPLE_CHARS = 65536


def detect_delimiter(sample: str) -> str:
    candidates = []
    for delimiter in (',', ';', '\t', '|'):
        try:
            # Preserve CR, LF and CRLF just as the actual file reader does.
            records = list(islice(csv.reader(io.StringIO(sample, newline=''), delimiter=delimiter), 21))
        except csv.Error:
            continue
        if not records or len(records[0]) < 2:
            continue
        width = len(records[0])
        # A bounded text sample can end halfway through its last record.
        rows = [row for row in records[1:-1] if row]
        consistent = sum(len(row) == width for row in rows)
        score = consistent / len(rows) if rows else 1.0
        candidates.append((score, consistent, width, delimiter))
    if not candidates:
        return ','  # A valid one-column CSV needs no separator.
    candidates.sort(reverse=True)
    best = candidates[0]
    ties = [item for item in candidates if item[:2] == best[:2]]
    if len(ties) > 1:
        try:
            detected = csv.Sniffer().sniff(sample, delimiters=''.join(item[3] for item in ties)).delimiter
            return detected
        except csv.Error:
            pass
    return best[3]


def csv_reader(stream: TextIO):
    position = stream.tell()
    sample = stream.read(SAMPLE_CHARS)
    stream.seek(position)
    return csv.reader(stream, delimiter=detect_delimiter(sample), strict=True)


def read_header(reader) -> list[str]:
    header = next(reader, None)
    if not header or any(not name.strip() for name in header):
        raise ValueError('CSV must contain non-empty column names')
    if len(set(header)) != len(header):
        raise ValueError('CSV contains duplicate column names')
    return header


def checked_rows(reader, header):
    for row in reader:
        if not row:  # Empty physical lines are not data records.
            continue
        if len(row) != len(header):
            raise ValueError(f'CSV row ending at line {reader.line_num} has {len(row)} fields; expected {len(header)}')
        yield dict(zip(header, row))
