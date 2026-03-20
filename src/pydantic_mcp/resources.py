from __future__ import annotations

import json
from textwrap import dedent

from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, Response

from .helpers import (
    MIGRATION_RULES,
    build_capabilities,
    build_health_payload,
    explain_model_data,
    registry_entries_to_summaries,
    resolve_target,
)
from .runtime import ERROR_HISTORY, REGISTRY, SERVER_SETTINGS, mcp


@mcp.custom_route(
    SERVER_SETTINGS.http_health_path,
    methods=["GET"],
    include_in_schema=False,
)
async def http_health(_request: StarletteRequest) -> Response:
    return JSONResponse(build_health_payload(), status_code=200)


@mcp.custom_route(
    SERVER_SETTINGS.http_ready_path,
    methods=["GET"],
    include_in_schema=False,
)
async def http_readiness(_request: StarletteRequest) -> Response:
    return JSONResponse(build_health_payload(), status_code=200)


@mcp.resource("pydantic://server/capabilities", mime_type="application/json")
def server_capabilities() -> str:
    return json.dumps(
        build_capabilities(SERVER_SETTINGS).model_dump(mode="json"),
        indent=2,
    )


@mcp.resource("pydantic://project/settings", mime_type="application/json")
def project_settings() -> str:
    return json.dumps(SERVER_SETTINGS.model_dump(mode="json"), indent=2)


@mcp.resource("pydantic://project/import-roots", mime_type="application/json")
def project_import_roots() -> str:
    return json.dumps(
        {
            "allowed_import_roots": SERVER_SETTINGS.allowed_import_roots,
            "default_scan_packages": SERVER_SETTINGS.default_scan_packages,
        },
        indent=2,
    )


@mcp.resource("pydantic://project/errors/recent", mime_type="application/json")
def recent_errors() -> str:
    return json.dumps(
        [record.model_dump(mode="json") for record in ERROR_HISTORY.list()],
        indent=2,
    )


@mcp.resource("pydantic://migration/rules", mime_type="application/json")
def migration_rules() -> str:
    payload = [
        {
            "legacy_pattern": legacy,
            "replacement": replacement,
            "severity": severity,
            "message": message,
        }
        for legacy, replacement, severity, message in MIGRATION_RULES
    ]
    return json.dumps(payload, indent=2)


@mcp.resource("pydantic://models/index", mime_type="application/json")
def models_index() -> str:
    entries = REGISTRY.discover(SERVER_SETTINGS.default_scan_packages)
    return json.dumps(
        [
            item.model_dump(mode="json")
            for item in registry_entries_to_summaries(entries)
        ],
        indent=2,
    )


@mcp.resource("pydantic://project/models/changed", mime_type="application/json")
def changed_models() -> str:
    entries = REGISTRY.discover(SERVER_SETTINGS.default_scan_packages)
    models = sorted(
        (
            {
                "qualified_name": entry.qualified_name,
                "module": entry.module,
                "module_file": entry.module_file,
                "modified_time": entry.modified_time,
            }
            for entry in entries.values()
        ),
        key=lambda item: (item["modified_time"] or 0.0, item["qualified_name"]),
        reverse=True,
    )
    return json.dumps(models, indent=2)


@mcp.resource(
    "pydantic://models/{qualified_name}",
    mime_type="application/json",
)
def model_metadata(qualified_name: str) -> str:
    runtime_target = resolve_target(
        qualified_name,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    payload = explain_model_data(
        runtime_target,
        include_constraints=True,
        include_defaults=True,
    )
    return json.dumps(payload, indent=2, default=repr)


@mcp.resource(
    "pydantic://schemas/{qualified_name}{?mode}",
    mime_type="application/json",
)
def model_schema(qualified_name: str, mode: str = "validation") -> str:
    runtime_target = resolve_target(
        qualified_name,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    schema = runtime_target.adapter.json_schema(mode=mode)
    return json.dumps(schema, indent=2, default=repr)


@mcp.resource(
    "pydantic://examples/{qualified_name}",
    mime_type="application/json",
)
def model_examples(qualified_name: str) -> str:
    runtime_target = resolve_target(
        qualified_name,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    from .helpers import create_examples

    payload = [
        item.model_dump(mode="json")
        for item in create_examples(runtime_target, count=1, invalid=True)
    ]
    return json.dumps(payload, indent=2, default=repr)


@mcp.resource("pydantic://reference/overview")
def reference_overview() -> str:
    return dedent(
        """
        # pydantic-mcp

        Purpose:
        - Discover and explain Pydantic models and Python type contracts.
        - Validate and serialize payloads with BaseModel or TypeAdapter behavior.
        - Generate JSON Schema and migration guidance for Pydantic v2 workflows.

        Suggested workflow:
        1. `list_models`
        2. `inspect_type`
        3. `explain_model`
        4. `validate_data`
        5. `serialize_data`
        6. `generate_json_schema`
        7. `compare_validation_modes`
        8. `create_example_payload`
        9. `migrate_v1_to_v2`

        Useful resources:
        - `pydantic://server/capabilities`
        - `pydantic://models/index`
        - `pydantic://models/{qualified_name}`
        - `pydantic://schemas/{qualified_name}?mode=validation`
        - `pydantic://examples/{qualified_name}`
        - `pydantic://migration/rules`
        """
    ).strip()
