"""Reproducible local audit of CSV sources without retaining their rows."""

from __future__ import annotations

import csv
from datetime import date, datetime
import hashlib
import io
from pathlib import Path
import re
from typing import Any

from app.data_sources.csv_format import detect_delimiter


_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_ID_NAME = re.compile(r"(^|[_\s-])(id|код|идентификатор)([_\s-]|$)", re.IGNORECASE)


def _decode_csv(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig"), "utf-8-sig"
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16"), "utf-16"
    for encoding in ("utf-8", "cp1251"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        return text, encoding
    if b"\x00" in content:
        try:
            return content.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    raise ValueError("CSV encoding is not supported; expected UTF-8, UTF-16, or Windows-1251")


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


def _inferred_type(values: list[str]) -> str:
    if not values:
        return "unknown"
    if all(_is_date(value) for value in values):
        return "date"
    if all(_DECIMAL_COMMA.fullmatch(value) for value in values):
        return "decimal_comma"
    if all(_INTEGER.fullmatch(value) for value in values) and not any(
        len(value.lstrip("+-")) > 1 and value.lstrip("+-").startswith("0")
        for value in values
    ):
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
            if row_count and field["null_count"] == 0 and len(distinct_values[name]) == row_count:
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
    content = path.read_bytes()
    text, encoding = _decode_csv(content)
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header = next(reader, None)
    if not header or any(not name.strip() for name in header):
        raise ValueError(f"{path.name}: CSV must contain non-empty column names")
    if len(set(header)) != len(header):
        raise ValueError(f"{path.name}: CSV contains duplicate column names")

    values = {name: [] for name in header}
    distinct_values = {name: set() for name in header}
    null_counts = {name: 0 for name in header}
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
            else:
                values[name].append(value)
                distinct_values[name].add(value)

    schema = [
        {
            "name": name,
            "inferred_type": _inferred_type(values[name]),
            "null_count": null_counts[name],
        }
        for name in header
    ]
    semantic_candidates, grain_candidates = _semantic_candidates(
        schema, row_count=row_count, distinct_values=distinct_values,
    )
    return {
        "name": path.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
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
