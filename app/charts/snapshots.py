"""Source version stamps for persisted chart results."""

from __future__ import annotations

from typing import Any

from app.schema_catalog import SchemaCatalog


def source_ids(definition: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("source_id"), str):
                found.add(value["source_id"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(definition)
    return found


def source_versions(catalog: SchemaCatalog, definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    versions: dict[str, dict[str, Any]] = {}
    for source_id in sorted(source_ids(definition)):
        source = catalog.get_source(source_id)
        versions[source_id] = {
            "snapshot_id": source.snapshot_id if source else None,
            "schema_version": source.schema_version if source else None,
        }
    return versions
