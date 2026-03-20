from __future__ import annotations

import argparse
from typing import Any

from .constants import SERVER_NAME, SERVER_VERSION
from .helpers import build_capabilities
from .runtime import SERVER_SETTINGS, mcp
from . import resources as _resources
from . import tools as _tools

list_models = _tools.list_models
inspect_type = _tools.inspect_type
explain_model = _tools.explain_model
validate_data = _tools.validate_data
serialize_data = _tools.serialize_data
generate_json_schema = _tools.generate_json_schema
create_example_payload = _tools.create_example_payload
compare_validation_modes = _tools.compare_validation_modes
migrate_v1_to_v2 = _tools.migrate_v1_to_v2
parse_partial_json = _tools.parse_partial_json
server_capabilities = _resources.server_capabilities
models_index = _resources.models_index
model_metadata = _resources.model_metadata
model_schema = _resources.model_schema
model_examples = _resources.model_examples
reference_overview = _resources.reference_overview
project_settings = _resources.project_settings
project_import_roots = _resources.project_import_roots
recent_errors = _resources.recent_errors
migration_rules = _resources.migration_rules
changed_models = _resources.changed_models

__all__ = [
    "SERVER_NAME",
    "SERVER_SETTINGS",
    "SERVER_VERSION",
    "build_capabilities",
    "changed_models",
    "compare_validation_modes",
    "create_example_payload",
    "explain_model",
    "generate_json_schema",
    "inspect_type",
    "list_models",
    "main",
    "mcp",
    "migrate_v1_to_v2",
    "migration_rules",
    "model_examples",
    "model_metadata",
    "model_schema",
    "models_index",
    "parse_partial_json",
    "project_import_roots",
    "project_settings",
    "recent_errors",
    "reference_overview",
    "serialize_data",
    "server_capabilities",
    "validate_data",
]


@mcp.prompt(
    name="explain model",
    description="Explain a model's fields, constraints, defaults, aliases, and edge cases.",
)
def explain_model_prompt(target: str) -> str:
    return (
        f"Explain the Pydantic target `{target}`. Cover fields, required vs optional,"
        " defaults, aliases, validators, serializers, nested models, and likely edge cases."
    )


@mcp.prompt(
    name="generate api contract docs",
    description="Turn a model or schema into docs for API consumers.",
)
def generate_api_contract_docs_prompt(target: str) -> str:
    return (
        f"Generate concise API contract documentation for `{target}`."
        " Include field meanings, example payloads, validation constraints, and serialization notes."
    )


@mcp.prompt(
    name="debug validation error",
    description="Given a validation trace, suggest the smallest payload fix.",
)
def debug_validation_error_prompt(target: str, error_summary: str) -> str:
    return (
        f"Target: `{target}`.\n"
        f"Validation trace:\n{error_summary}\n\n"
        "Suggest the minimum payload change that would make validation succeed."
    )


@mcp.prompt(
    name="design a model from example json",
    description="Infer a candidate Pydantic model from sample payloads.",
)
def design_model_from_example_json_prompt(example_json: str) -> str:
    return (
        "Design a Pydantic v2 model from this JSON example. "
        "Prefer explicit field types, sensible optionals, and modern `model_config` usage.\n\n"
        f"{example_json}"
    )


@mcp.prompt(
    name="review schema compatibility",
    description="Compare two models or schemas for breaking changes.",
)
def review_schema_compatibility_prompt(before: str, after: str) -> str:
    return (
        f"Compare `{before}` and `{after}` for breaking schema changes. "
        "Call out removed fields, stricter constraints, alias changes, and nullability differences."
    )


@mcp.prompt(
    name="migrate to pydantic v2",
    description="Inspect code and produce a migration checklist.",
)
def migrate_to_pydantic_v2_prompt(code: str) -> str:
    return (
        "Review this code for Pydantic v1 patterns and produce a migration checklist for v2. "
        "Include API replacements, config changes, validator changes, and risk level.\n\n"
        f"{code}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=SERVER_NAME)
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default=SERVER_SETTINGS.default_transport,
    )
    parser.add_argument("--host", default=SERVER_SETTINGS.default_host)
    parser.add_argument("--port", type=int, default=SERVER_SETTINGS.default_port)
    parser.add_argument("--path", default=SERVER_SETTINGS.default_path)
    args = parser.parse_args(argv)

    transport_kwargs: dict[str, Any] = {}
    if args.transport != "stdio":
        transport_kwargs["host"] = args.host
        transport_kwargs["port"] = args.port
        if args.path:
            transport_kwargs["path"] = args.path
    mcp.run(args.transport, **transport_kwargs)
