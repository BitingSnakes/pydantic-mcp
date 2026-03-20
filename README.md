# pydantic-mcp

`pydantic-mcp` is an MCP server for inspecting Pydantic models and Python type contracts. It is built for LLM workflows that need deterministic validation, serialization, schema generation, model explanations, and migration help.

## Features

- Discover Pydantic `BaseModel` classes across configured packages.
- Resolve targets from import paths, short model names, Python type expressions, or inline model snippets.
- Validate arbitrary payloads with `TypeAdapter` or model behavior.
- Serialize validated data in Python or JSON mode.
- Generate validation and serialization JSON Schema.
- Explain fields, defaults, aliases, decorators, constraints, and nested models.
- Generate valid and invalid example payloads.
- Compare strict/non-strict and Python-vs-JSON validation behavior.
- Analyze common Pydantic v1 to v2 migration issues.
- Parse partial JSON with `pydantic_core.from_json`.
- Expose MCP tools, resources, prompts, plus HTTP health/readiness routes.

## Tools

- `list_models`
- `inspect_type`
- `explain_model`
- `validate_data`
- `serialize_data`
- `generate_json_schema`
- `create_example_payload`
- `compare_validation_modes`
- `migrate_v1_to_v2`
- `parse_partial_json`

## Resources

- `pydantic://server/capabilities`
- `pydantic://project/settings`
- `pydantic://project/import-roots`
- `pydantic://project/errors/recent`
- `pydantic://project/models/changed`
- `pydantic://models/index`
- `pydantic://models/{qualified_name}`
- `pydantic://schemas/{qualified_name}?mode=validation|serialization`
- `pydantic://examples/{qualified_name}`
- `pydantic://migration/rules`
- `pydantic://reference/overview`

## Prompts

- `explain model`
- `generate api contract docs`
- `debug validation error`
- `design a model from example json`
- `review schema compatibility`
- `migrate to pydantic v2`

## Run

Install dependencies:

```bash
uv sync
```

Run over stdio:

```bash
uv run python mcp_server.py --transport stdio
```

Run over HTTP:

```bash
uv run python mcp_server.py --transport http --host 127.0.0.1 --port 8000
```

Health endpoints:

- `GET /healthz`
- `GET /readyz`

## Configuration

Important environment variables:

- `PYDANTIC_MCP_ALLOWED_IMPORT_ROOTS`
- `PYDANTIC_MCP_DEFAULT_SCAN_PACKAGES`
- `PYDANTIC_MCP_IMPORT_TIMEOUT_SECONDS`
- `PYDANTIC_MCP_ERROR_HISTORY_LIMIT`
- `PYDANTIC_MCP_TRANSPORT`
- `PYDANTIC_MCP_HOST`
- `PYDANTIC_MCP_PORT`

Example:

```bash
PYDANTIC_MCP_ALLOWED_IMPORT_ROOTS=tests.fixtures.sample_app \
PYDANTIC_MCP_DEFAULT_SCAN_PACKAGES=tests.fixtures.sample_app \
uv run python mcp_server.py --transport stdio
```

## Testing

```bash
just test
```
