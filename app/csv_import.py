"""Stream and validate CSV bytes while retaining an exact original artifact."""

from __future__ import annotations

import codecs
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
import re
from typing import BinaryIO

from app.data_sources.csv_format import SAMPLE_CHARS, detect_delimiter, read_header
from app.models import ImportReport


MAX_CSV_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
_INTEGER = re.compile(r"^[+-]?\d+$")
_AMBIGUOUS_DATE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")
_SEP = re.compile(r"^sep=([,;\t|])\s*$", re.IGNORECASE)


class CSVImportError(ValueError):
    def __init__(self, message: str, report: ImportReport, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.report = report
        self.status_code = status_code


def copy_original(stream: BinaryIO, target: Path) -> ImportReport:
    """Copy in bounded chunks and hash the exact uploaded bytes."""
    report = ImportReport()
    digest = sha256()
    with target.open("xb") as destination:
        while chunk := stream.read(CHUNK_BYTES):
            report.size_bytes += len(chunk)
            if report.size_bytes > MAX_CSV_BYTES:
                raise CSVImportError("CSV exceeds the 512 MiB upload limit", report, status_code=413)
            destination.write(chunk)
            digest.update(chunk)
    report.sha256 = digest.hexdigest()
    if not report.size_bytes:
        raise CSVImportError("Uploaded CSV is empty", report)
    return report


def detect_encoding(path: Path) -> str:
    with path.open("rb") as stream:
        sample = stream.read(SAMPLE_CHARS)
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if b"\x00" in sample:
        even_nuls = sample[0::2].count(0)
        odd_nuls = sample[1::2].count(0)
        return "utf-16-le" if odd_nuls > even_nuls else "utf-16-be"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def _date_type(value: str) -> str | None:
    try:
        if ("T" in value or " " in value) and datetime.fromisoformat(value.replace("Z", "+00:00")):
            return "datetime"
        date.fromisoformat(value)
        return "date"
    except ValueError:
        return None


class _ColumnState:
    def __init__(self) -> None:
        self.values = 0
        self.empty = 0
        self.integer = True
        self.decimal = True
        self.boolean = True
        self.date = True
        self.datetime = True
        self.leading_zero = False
        self.ambiguous_date = False
        self.digits_before = 0
        self.scale = 0
        self.sample: list[str] = []

    def add(self, value: str) -> None:
        if not value.strip():
            self.empty += 1
            return
        self.values += 1
        if len(self.sample) < 500:
            self.sample.append(value)
        stripped = value.strip()
        is_integer = bool(_INTEGER.fullmatch(stripped))
        self.integer &= is_integer
        unsigned = stripped.lstrip("+-")
        self.leading_zero |= is_integer and len(unsigned) > 1 and unsigned.startswith("0")
        self.boolean &= stripped.casefold() in {"true", "false", "yes", "no"}
        parsed_date = _date_type(stripped)
        self.date &= parsed_date == "date"
        self.datetime &= parsed_date == "datetime"
        self.ambiguous_date |= bool(_AMBIGUOUS_DATE.fullmatch(stripped))
        try:
            number = Decimal(stripped.replace(",", "."))
            if not number.is_finite():
                raise InvalidOperation
            exponent = number.as_tuple().exponent
            scale = max(0, -exponent)
            digits_before = max(1, len(number.as_tuple().digits) + exponent)
            self.scale = max(self.scale, scale)
            self.digits_before = max(self.digits_before, digits_before)
        except (InvalidOperation, ValueError):
            self.decimal = False

    def inferred_type(self) -> str:
        if not self.values:
            return "unknown"
        if self.leading_zero:
            return "string"
        if self.boolean:
            return "boolean"
        if self.integer and self.decimal:
            return "integer"
        if self.decimal:
            return "number"
        if self.date:
            return "date"
        if self.datetime:
            return "datetime"
        return "string"

    def sql_type(self) -> str:
        kind = self.inferred_type()
        if kind == "integer":
            return "BIGINT" if self.digits_before <= 18 else "DECIMAL(38,0)" if self.digits_before <= 38 else "VARCHAR"
        if kind == "number":
            return f"DECIMAL(38,{self.scale})" if self.digits_before + self.scale <= 38 else "VARCHAR"
        return {"boolean": "BOOLEAN", "date": "DATE", "datetime": "TIMESTAMP"}.get(kind, "VARCHAR")


def _scan_with_encoding(original: Path, normalized: Path, encoding: str, report: ImportReport) -> ImportReport:
    report.encoding = encoding
    with original.open("r", encoding=encoding, newline="") as source:
        first_line = source.readline()
        directive = _SEP.fullmatch(first_line.rstrip("\r\n"))
        if directive:
            delimiter = directive.group(1)
        else:
            source.seek(0)
            sample = source.read(SAMPLE_CHARS)
            source.seek(0)
            delimiter = detect_delimiter(sample)
        report.delimiter = delimiter
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        try:
            header = read_header(reader)
        except (ValueError, csv.Error) as exc:
            raise CSVImportError(str(exc), report) from exc
        states = {name: _ColumnState() for name in header}
        with normalized.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(header)
            try:
                for row in reader:
                    if not row:
                        report.blank_lines += 1
                        continue
                    report.rows_read += 1
                    if len(row) != len(header):
                        report.rejected_rows += 1
                        if len(report.errors) < 20:
                            report.errors.append(
                                f"CSV row ending at line {reader.line_num} has {len(row)} fields; expected {len(header)}"
                            )
                        continue
                    report.accepted_rows += 1
                    writer.writerow(row)
                    for name, value in zip(header, row, strict=True):
                        states[name].add(value)
            except csv.Error as exc:
                report.rows_read += 1
                report.rejected_rows += 1
                report.errors.append(f"CSV quoting error near line {reader.line_num}: {exc}")
    if report.blank_lines:
        report.warnings.append(f"blank_lines: {report.blank_lines} empty physical lines were ignored")
    if report.accepted_rows == 0 and not report.errors:
        report.warnings.append("no_data_rows: CSV has a header but no data rows")
    for name, state in states.items():
        kind = state.inferred_type()
        report.column_types[name] = kind
        report.column_nullable[name] = state.empty > 0
        report.typed_sql_types[name] = state.sql_type()
        if state.ambiguous_date and kind == "string":
            report.warnings.append(f"ambiguous_date: {name} remains text")
        if state.sample and kind != _sample_type(state.sample):
            report.warnings.append(f"mixed_tail: {name} changed from {_sample_type(state.sample)} to {kind} during full scan")
        if kind in {"number", "integer"} and state.sql_type() == "VARCHAR":
            report.warnings.append(f"precision_overflow: {name} remains text")
    if report.errors:
        raise CSVImportError(report.errors[0], report)
    return report


def _sample_type(values: list[str]) -> str:
    sample = _ColumnState()
    for value in values:
        sample.add(value)
    return sample.inferred_type()


def scan_csv(original: Path, normalized: Path, report: ImportReport) -> ImportReport:
    encoding = detect_encoding(original)
    try:
        return _scan_with_encoding(original, normalized, encoding, report)
    except UnicodeDecodeError as exc:
        if encoding not in {"utf-8", "utf-8-sig"}:
            raise CSVImportError("CSV contains invalid encoding", report) from exc
        # An ASCII prefix can hide a Windows-1251 byte after the sample.
        fresh = ImportReport(sha256=report.sha256, size_bytes=report.size_bytes)
        return _scan_with_encoding(original, normalized, "cp1251", fresh)
