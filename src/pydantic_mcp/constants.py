from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from textwrap import dedent
import tomllib

SERVER_NAME = "pydantic-mcp"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_HTTP_HEALTH_PATH = "/healthz"
DEFAULT_HTTP_READY_PATH = "/readyz"
DEFAULT_IMPORT_TIMEOUT_SECONDS = 5.0
DEFAULT_ERROR_HISTORY_LIMIT = 32
VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _load_server_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as pyproject_file:
            pyproject_data = tomllib.load(pyproject_file)
        return str(pyproject_data["project"]["version"])

    return metadata.version(SERVER_NAME)


SERVER_VERSION = _load_server_version()

SERVER_INSTRUCTIONS = dedent(
    """
    Use this server as a Pydantic contract workbench.
    It is designed to help an MCP client inspect models and Python type hints,
    validate payloads, explain constraints, compare validation behavior, generate
    JSON Schema, and surface migration guidance from Pydantic v1 to v2.

    Core capabilities:
    - Discover Pydantic models in configured Python packages.
    - Resolve a target from an import path, short model name, Python type expression,
      or inline code snippet.
    - Validate arbitrary Python or JSON inputs with BaseModel or TypeAdapter behavior.
    - Serialize validated data in Python-mode or JSON-mode.
    - Generate validation and serialization JSON Schema variants.
    - Explain fields, defaults, aliases, constraints, decorators, and nested types.
    - Produce example valid and invalid payloads to ground downstream prompts.
    - Inspect migration risks and partial JSON parsing behavior.

    Recommended workflow:
    1. Use `list_models` to discover candidates in the project.
    2. Use `inspect_type` or `explain_model` to understand the target contract.
    3. Call `validate_data` with representative payloads before generating schema docs.
    4. Use `serialize_data` and `generate_json_schema` to compare runtime and schema behavior.
    5. When debugging ambiguity, use `compare_validation_modes`.
    6. Use `create_example_payload` for test fixtures and prompt grounding.
    7. Use `migrate_v1_to_v2` when the codebase still contains legacy APIs.

    Operating guidance:
    - Prefer deterministic tool calls with explicit `target` values.
    - Use `list_models` before relying on a short model name alias.
    - Treat `TypeAdapter` as the default abstraction for arbitrary type hints.
    - Prefer `strict=true` when diagnosing coercion surprises.
    - Compare validation-mode and serialization-mode schema when API compatibility matters.
    - Inline code snippets are supported for exploration, but import-path targets are more stable.
    """
).strip()
