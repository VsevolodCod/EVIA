"""Reproducible local audit of CSV sources without retaining their rows."""

from __future__ import annotations

import csv
import codecs
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from typing import Any

from app.data_sources.csv_format import SAMPLE_CHARS, detect_delimiter


_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_ID_NAME = re.compile(r"(^|[_\s-])(id|код|идентификатор)([_\s-]|$)", re.IGNORECASE)


def _detect_encoding(path: Path) -> str:
    """Identify supported encodings from a small byte sample.

    The full source is deliberately not decoded into memory: one of the source
    datasets is hundreds of megabytes and the audit only needs aggregates.
    """
    with path.open("rb") as stream:
        sample = stream.read(SAMPLE_CHARS)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in sample:
        return "utf-16"
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        decoder.decode(sample, final=False)
    except UnicodeDecodeError:
        return "cp1251"
    return "utf-8"


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False


def _inferred_type(
    *, has_values: bool, all_dates: bool, all_decimal_commas: bool, all_integers: bool, has_leading_zero: bool,
) -> str:
    if not has_values:
        return "unknown"
    if all_dates:
        return "date"
    if all_decimal_commas:
        return "decimal_comma"
    if all_integers and not has_leading_zero:
        return "integer"
    return "string"


def _semantic_candidates(
    fields: list[dict[str, Any]], *, row_count: int, distinct_values: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    labels: set[str] = set()
    grain_candidates: list[str] = []
    for field in fields:
        name = field["name"]
        normalized = name.casefold()
        inferred_type = field["inferred_type"]
        if _ID_NAME.search(normalized):
            labels.add("identifier")
            if row_count and field["null_count"] == 0 and len(distinct_values.get(name, set())) == row_count:
                grain_candidates.append(name)
        if inferred_type == "date" or any(token in normalized for token in ("date", "дата", "time", "время")):
            labels.add("date")
        if inferred_type == "decimal_comma":
            labels.add("decimal")
        if any(token in normalized for token in ("return", "refund", "возврат")):
            labels.add("return")
        if any(token in normalized for token in ("event", "событ")):
            labels.add("event")
        if any(token in normalized for token in ("session", "сесси")):
            labels.add("session")
        if any(token in normalized for token in ("attempt", "попыт")):
            labels.add("attempt")
        if any(token in normalized for token in ("chain", "цепоч")):
            labels.add("chain")
    if grain_candidates:
        labels.add("grain")
    return sorted(labels), grain_candidates


def audit_csv(path: Path) -> dict[str, Any]:
    """Return metadata and aggregate field statistics, never source rows."""
    encoding = _detect_encoding(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    size_bytes = path.stat().st_size

    with path.open("r", encoding=encoding, newline="") as source:
        sample = source.read(SAMPLE_CHARS)
        source.seek(0)
        delimiter = detect_delimiter(sample)
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header or any(not name.strip() for name in header):
            raise ValueError(f"{path.name}: CSV must contain non-empty column names")
        if len(set(header)) != len(header):
            raise ValueError(f"{path.name}: CSV contains duplicate column names")

        identifier_fields = {name for name in header if _ID_NAME.search(name.casefold())}
        distinct_values = {name: set() for name in identifier_fields}
        null_counts = {name: 0 for name in header}
        states = {
            name: {"has_values": False, "all_dates": True, "all_decimal_commas": True,
                   "all_integers": True, "has_leading_zero": False}
            for name in header
        }
        row_count = 0
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"{path.name}: row ending at line {reader.line_num} has {len(row)} fields; expected {len(header)}",
                )
            row_count += 1
            for name, value in zip(header, row, strict=True):
                if value == "":
                    null_counts[name] += 1
                    continue
                state = states[name]
                state["has_values"] = True
                state["all_dates"] = state["all_dates"] and _is_date(value)
                state["all_decimal_commas"] = state["all_decimal_commas"] and bool(_DECIMAL_COMMA.fullmatch(value))
                state["all_integers"] = state["all_integers"] and bool(_INTEGER.fullmatch(value))
                unsigned_value = value.lstrip("+-")
                state["has_leading_zero"] = state["has_leading_zero"] or (
                    len(unsigned_value) > 1 and unsigned_value.startswith("0")
                )
                if name in distinct_values:
                    distinct_values[name].add(value)

    schema = [{"name": name, "inferred_type": _inferred_type(**states[name]), "null_count": null_counts[name]}
              for name in header]
    semantic_candidates, grain_candidates = _semantic_candidates(
        schema, row_count=row_count, distinct_values=distinct_values,
    )
    return {
        "name": path.name,
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
        "encoding": encoding,
        "delimiter": delimiter,
        "row_count": row_count,
        "schema": schema,
        "semantic_candidates": semantic_candidates,
        "candidate_grain_keys": grain_candidates,
    }


def audit_directory(directory: Path, *, expected_files: int = 9) -> dict[str, Any]:
    """Audit a local set of CSV files, requiring its expected cardinality."""
    files = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.casefold() == ".csv")
    if len(files) != expected_files:
        raise ValueError(f"Expected {expected_files} CSV files, found {len(files)}")
    return {
        "format_version": 1,
        "file_count": len(files),
        "files": [audit_csv(path) for path in files],
    }


def write_public_method_report() -> str:
    """Describe the procedure without publishing source filenames, headers or rows."""
    return """# Метод аудита исходных CSV

Локальный аудитор фиксирует для каждого файла SHA-256, размер, кодировку,
разделитель, число строк и агрегированную схему. Он не сохраняет и не
публикует raw rows, значения ячеек или исходные CSV.

Повторный запуск над теми же байтами должен вернуть те же hash и metadata.
Кандидаты ключей, grain, дат, десятичных значений, NULL, возвратов, событий,
сессий, попыток и цепочек являются эвристиками для последующей проверки
командой данных: они не подтверждают бизнес-смысл автоматически.

Ограничения: распознаются UTF-8, UTF-8 BOM, UTF-16 и Windows-1251; сложные
форматы и неоднозначные разделители требуют ручной проверки. Публичный отчёт
не содержит имён файлов, заголовков или сведений, позволяющих восстановить
данные.
"""
