"""Source version stamps for persisted chart results."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


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


def source_versions(
    catalog: SchemaCatalog, definition: dict[str, Any], *, sources: SourceService | None = None,
) -> dict[str, dict[str, Any]]:
    versions: dict[str, dict[str, Any]] = {}
    for source_id in sorted(source_ids(definition)):
        source = catalog.get_source(source_id)
        versions[source_id] = {
            "snapshot_id": source.snapshot_id if source else None,
            "schema_version": source.schema_version if source else None,
        }
        if source and source.source_type == "postgresql":
            # The catalog's integer version is fixed for live tables. Probe the
            # allowlisted table again so DDL does not silently reuse old data.
            try:
                if sources is None or sources.postgres_adapter is None:
                    raise ValueError("PostgreSQL adapter is unavailable")
                schema = sources.postgres_adapter.introspect_schema(source)
                structure = [
                    {
                        "name": obj.name,
                        "type": obj.object_type,
                        "fields": [
                            {"name": field.name, "type": field.inferred_type, "nullable": field.nullable}
                            for field in obj.fields
                        ],
                    }
                    for obj in schema.objects
                ]
                encoded = json.dumps(structure, sort_keys=True, ensure_ascii=False).encode("utf-8")
                versions[source_id]["live_schema_fingerprint"] = sha256(encoded).hexdigest()
                versions[source_id]["schema_status"] = "available"
            except Exception:
                # Never persist driver exceptions: they may contain a DSN.
                versions[source_id]["live_schema_fingerprint"] = None
                versions[source_id]["schema_status"] = "unavailable"
    return versions
