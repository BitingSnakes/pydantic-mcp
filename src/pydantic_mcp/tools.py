from __future__ import annotations

import inspect

from .helpers import (
    compare_validation_modes as build_validation_comparison,
    create_examples,
    describe_type,
    explain_model_data,
    generate_model_from_json_report,
    make_response,
    migration_report,
    parse_partial_json_report,
    registry_entries_to_summaries,
    resolve_target,
    serialize_with_adapter,
    validate_with_adapter,
    build_schema_report,
)
from .models import Diagnostic, ErrorRecord, ToolResponse
from .runtime import ERROR_HISTORY, REGISTRY, SERVER_SETTINGS, mcp


def _record_response_errors(
    tool_name: str, target: str | None, response: ToolResponse
) -> None:
    errors = [
        item for item in response.result.get("errors", []) if isinstance(item, dict)
    ]
    if response.diagnostics and any(
        item.level == "error" for item in response.diagnostics
    ):
        ERROR_HISTORY.add(
            ErrorRecord(
                tool_name=tool_name,
                target=target,
                message=response.diagnostics[0].message,
                issues=[normalize_issue_dict(item) for item in errors],
            )
        )
    elif errors:
        ERROR_HISTORY.add(
            ErrorRecord(
                tool_name=tool_name,
                target=target,
                message="Validation failed.",
                issues=[normalize_issue_dict(item) for item in errors],
            )
        )


def normalize_issue_dict(payload: dict) -> object:
    from .models import ValidationIssue

    return ValidationIssue.model_validate(payload)


@mcp.tool(tags={"discovery", "pydantic"})
def list_models(
    packages: list[str] | None = None,
    filter: str | None = None,
) -> ToolResponse:
    """Discover exported Pydantic models in configured packages."""
    package_list = packages or SERVER_SETTINGS.default_scan_packages
    entries = REGISTRY.discover(package_list)
    models = registry_entries_to_summaries(entries, pattern=filter)
    return make_response(
        diagnostics=[
            Diagnostic(
                level="info",
                message=f"Discovered {len(models)} model(s).",
                code="model_discovery",
            )
        ],
        artifacts={"packages": package_list},
        result={"models": [model.model_dump(mode="json") for model in models]},
    )


@mcp.tool(tags={"inspect", "pydantic"})
def inspect_type(
    target: str,
    expand_nested: bool = True,
) -> ToolResponse:
    """Resolve a Python type annotation or model into a structured description."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    return make_response(
        resolved_target=runtime_target.resolved,
        result={
            "type": describe_type(
                runtime_target.annotation,
                expand_nested=expand_nested,
            ).model_dump(mode="json")
        },
    )


@mcp.tool(tags={"inspect", "pydantic"})
def explain_model(
    target: str,
    include_examples: bool = True,
    include_constraints: bool = True,
    include_defaults: bool = True,
) -> ToolResponse:
    """Turn a model or type into a human-readable contract."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    result = explain_model_data(
        runtime_target,
        include_constraints=include_constraints,
        include_defaults=include_defaults,
    )
    if include_examples:
        result["examples"] = [
            item.model_dump(mode="json")
            for item in create_examples(runtime_target, count=1, invalid=True)
        ]
    return make_response(resolved_target=runtime_target.resolved, result=result)


@mcp.tool(tags={"validation", "pydantic"})
def validate_data(
    target: str,
    data: object,
    mode: str = "python",
    strict: bool = False,
    context: dict[str, object] | None = None,
) -> ToolResponse:
    """Validate input against a model name or Python type expression."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    response = validate_with_adapter(
        runtime_target,
        data=data,
        mode=mode,
        strict=strict,
        context=context,
    )
    _record_response_errors("validate_data", target, response)
    return response


@mcp.tool(tags={"serialization", "pydantic"})
def serialize_data(
    target: str,
    data: object,
    output_mode: str = "python",
    by_alias: bool = False,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    round_trip: bool = False,
) -> ToolResponse:
    """Dump validated data using Pydantic serialization behavior."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    response = serialize_with_adapter(
        runtime_target,
        data=data,
        output_mode=output_mode,
        by_alias=by_alias,
        exclude_unset=exclude_unset,
        exclude_defaults=exclude_defaults,
        exclude_none=exclude_none,
        round_trip=round_trip,
    )
    _record_response_errors("serialize_data", target, response)
    return response


@mcp.tool(tags={"schema", "pydantic"})
def generate_json_schema(
    target: str,
    schema_mode: str = "validation",
    include_definitions: bool = True,
) -> ToolResponse:
    """Generate JSON Schema for a model or type."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    return build_schema_report(
        runtime_target,
        schema_mode=schema_mode,
        include_definitions=include_definitions,
    )


@mcp.tool(tags={"examples", "pydantic"})
def create_example_payload(
    target: str,
    count: int = 1,
    invalid_examples: bool = False,
) -> ToolResponse:
    """Generate example valid and invalid payloads for a target model or type."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    examples = create_examples(runtime_target, count=count, invalid=invalid_examples)
    return make_response(
        resolved_target=runtime_target.resolved,
        result={"examples": [item.model_dump(mode="json") for item in examples]},
    )


@mcp.tool(tags={"comparison", "pydantic"})
def compare_validation_modes(
    target: str,
    data: object,
) -> ToolResponse:
    """Compare model, TypeAdapter, strict, and JSON-vs-Python validation behavior."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    response = build_validation_comparison(runtime_target, data=data)
    _record_response_errors("compare_validation_modes", target, response)
    return response


@mcp.tool(tags={"migration", "pydantic"})
def migrate_v1_to_v2(
    code: str | None = None,
    target: str | None = None,
    apply_fixes: bool = False,
) -> ToolResponse:
    """Analyze a snippet or model source for common Pydantic v1-to-v2 migration issues."""
    if code is None and target is None:
        return make_response(
            diagnostics=[
                Diagnostic(
                    level="error",
                    message="Provide either `code` or `target`.",
                    code="missing_input",
                )
            ],
            result={"findings": [], "risk_level": "none", "updated_code": None},
        )
    if code is None and target is not None:
        runtime_target = resolve_target(
            target,
            registry=REGISTRY,
            settings=SERVER_SETTINGS,
        )
        code = inspect.getsource(
            runtime_target.model_class or runtime_target.annotation
        )
        response = migration_report(code, apply_fixes=apply_fixes)
        response.resolved_target = runtime_target.resolved
        return response
    return migration_report(code or "", apply_fixes=apply_fixes)


@mcp.tool(tags={"json", "pydantic"})
def parse_partial_json(
    target: str,
    partial_json: str,
    allow_partial: bool = True,
) -> ToolResponse:
    """Best-effort parse partial JSON, then validate the parsed fragment."""
    runtime_target = resolve_target(
        target,
        registry=REGISTRY,
        settings=SERVER_SETTINGS,
    )
    response = parse_partial_json_report(
        runtime_target,
        partial_json=partial_json,
        allow_partial=allow_partial,
    )
    _record_response_errors("parse_partial_json", target, response)
    return response


@mcp.tool(tags={"generation", "json", "pydantic"})
def generate_model_from_json(
    json_input: object,
    model_name: str = "GeneratedModel",
) -> ToolResponse:
    """Infer candidate Pydantic models from a JSON string or JSON-like payload."""
    return generate_model_from_json_report(json_input, model_name=model_name)
