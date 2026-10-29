"""Stream and validate CSV bytes while retaining an exact original artifact."""

from __future__ import annotations

import codecs
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
import re
import shutil
from typing import BinaryIO

from app.data_sources.csv_format import SAMPLE_CHARS, detect_delimiter, read_header
from app.models import ImportReport


MAX_CSV_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
IMPORT_RESERVE_BYTES = 16 * 1024 * 1024
_INTEGER = re.compile(r"^[+-]?[0-9]+$")
_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)$")
_CALENDAR_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_AMBIGUOUS_DATE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")
_SEP = re.compile(r"^sep=([,;\t|])\s*$", re.IGNORECASE)


class CSVImportError(ValueError):
    def __init__(self, message: str, report: ImportReport, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.report = report
        self.status_code = status_code


def require_import_space(directory: Path, additional_bytes: int, report: ImportReport) -> None:
    """Best-effort headroom for originals, normalization and database writes.

    This is an estimate, not a disk reservation; concurrent writes may still fail.
    Keep a small reserve for catalog/WAL writes and cleanup.
    """
    if shutil.disk_usage(directory).free < additional_bytes + IMPORT_RESERVE_BYTES:
        raise CSVImportError("Insufficient storage for CSV import", report, status_code=507)


def copy_original(stream: BinaryIO, target: Path) -> ImportReport:
    """Copy in bounded chunks and hash the exact uploaded bytes."""
    report = ImportReport()
    digest = sha256()
    if stream.seekable():
        position = stream.tell()
        remaining = stream.seek(0, 2) - position
        stream.seek(position)
        if remaining > MAX_CSV_BYTES:
            raise CSVImportError("CSV exceeds the 512 MiB upload limit", report, status_code=413)
        require_import_space(target.parent, max(0, remaining) * 4, report)
    else:
        require_import_space(target.parent, 0, report)
    with target.open("xb") as destination:
        while chunk := stream.read(CHUNK_BYTES):
            report.size_bytes += len(chunk)
            if report.size_bytes > MAX_CSV_BYTES:
                raise CSVImportError("CSV exceeds the 512 MiB upload limit", report, status_code=413)
            require_import_space(target.parent, len(chunk) + report.size_bytes * 3, report)
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
        even_ratio = even_nuls / max(1, len(sample[0::2]))
        odd_ratio = odd_nuls / max(1, len(sample[1::2]))
        for encoding, count, ratio, opposite in (
            ("utf-16-le", odd_nuls, odd_ratio, even_ratio),
            ("utf-16-be", even_nuls, even_ratio, odd_ratio),
        ):
            if count < 2 or ratio < 0.1 or opposite >= 0.05:
                continue
            decoded = sample[:len(sample) - len(sample) % 2].decode(encoding, errors="ignore")
            if any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
                continue
            if any(char in decoded for char in ",;\t|\n\r"):
                return encoding
    # Cyrillic UTF-16 without a BOM can contain almost no NUL bytes: each
    # letter occupies two nonzero bytes. Decoding those bytes as UTF-8 may
    # still succeed, but produces a stream dominated by control characters.
    # A real UTF-16 line ending gives us an unambiguous byte-order signal.
    non_nul_controls = sum(byte < 32 and byte not in (0, 9, 10, 13) for byte in sample)
    if non_nul_controls / max(1, len(sample)) >= 0.15:
        candidates = []
        even_sample = sample[:len(sample) - len(sample) % 2]
        for encoding in ("utf-16-le", "utf-16-be"):
            decoded = even_sample.decode(encoding, errors="ignore")
            if "\n" not in decoded and "\r" not in decoded:
                continue
            if any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
                continue
            candidates.append(encoding)
        if len(candidates) == 1:
            return candidates[0]
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def _date_type(value: str) -> str | None:
    try:
        if "T" in value or " " in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "datetime" if parsed.tzinfo is None and _CALENDAR_DATE.fullmatch(value[:10]) else None
        if _CALENDAR_DATE.fullmatch(value):
            date.fromisoformat(value)
            return "date"
        return None
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
            if not _DECIMAL.fullmatch(stripped):
                raise InvalidOperation
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
    csv.field_size_limit(MAX_CSV_BYTES)
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
                    if report.rows_read % 1024 == 0:
                        require_import_space(normalized.parent, CHUNK_BYTES, report)
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
                    for name, value in zip(header, row, strict=True):
                        if value == null_marker(report.sha256):
                            report.rejected_rows += 1
                            report.errors.append(f"CSV value collides with reserved import marker at line {reader.line_num}")
                            raise CSVImportError(report.errors[-1], report)
                        states[name].add(value)
                    report.accepted_rows += 1
                    writer.writerow(row)
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


def null_marker(original_sha256: str) -> str:
    """A content-addressed marker cannot appear in its own file without a hash preimage."""
    return f"__EVIA_NULL_{original_sha256}__"


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
