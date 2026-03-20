from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from fastmcp import Client
from fastmcp.client import PythonStdioTransport

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOL_NAMES = {
    "list_models",
    "inspect_type",
    "explain_model",
    "validate_data",
    "serialize_data",
    "generate_json_schema",
    "create_example_payload",
    "generate_model_from_json",
    "compare_validation_modes",
    "migrate_v1_to_v2",
    "parse_partial_json",
}


@contextmanager
def _run_server(*args: str, env: dict[str, str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "mcp_server.py", *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def _wait_for_health(url: str, *, timeout_seconds: float = 15.0) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {url}")


async def _collect_stdio_surface() -> tuple[
    set[str], list[object], list[object], list[object]
]:
    env = os.environ.copy()
    env["PYDANTIC_MCP_ALLOWED_IMPORT_ROOTS"] = "tests.fixtures.sample_app"
    env["PYDANTIC_MCP_DEFAULT_SCAN_PACKAGES"] = "tests.fixtures.sample_app"
    transport = PythonStdioTransport(
        script_path=str(ROOT / "mcp_server.py"),
        env=env,
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        resource_templates = await client.list_resource_templates()
        prompts = await client.list_prompts()
        return {tool.name for tool in tools}, resources, resource_templates, prompts


def test_stdio_server_exposes_expected_tools_resources_and_prompts() -> None:
    tool_names, resources, resource_templates, prompts = asyncio.run(
        _collect_stdio_surface()
    )

    assert tool_names == EXPECTED_TOOL_NAMES
    assert any(str(resource.uri) == "pydantic://models/index" for resource in resources)
    assert any(
        str(resource.uriTemplate) == "pydantic://models/{qualified_name}"
        for resource in resource_templates
    )
    assert any(prompt.name == "explain model" for prompt in prompts)
    assert any(prompt.name == "migrate to pydantic v2" for prompt in prompts)


def test_http_server_exposes_health_route() -> None:
    env = os.environ.copy()
    env["PYDANTIC_MCP_ALLOWED_IMPORT_ROOTS"] = "tests.fixtures.sample_app"
    env["PYDANTIC_MCP_DEFAULT_SCAN_PACKAGES"] = "tests.fixtures.sample_app"
    with _run_server("--transport", "http", "--port", "8123", env=env):
        payload = _wait_for_health("http://127.0.0.1:8123/healthz")

    assert payload["status"] == "ok"
