from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import (
    DEFAULT_ERROR_HISTORY_LIMIT,
    DEFAULT_HTTP_HEALTH_PATH,
    DEFAULT_HTTP_READY_PATH,
    DEFAULT_IMPORT_TIMEOUT_SECONDS,
    DEFAULT_LOG_LEVEL,
    VALID_LOG_LEVELS,
)


class ServerSettings(BaseModel):
    log_level: str = DEFAULT_LOG_LEVEL
    mask_error_details: bool = True
    strict_input_validation: bool = True
    default_transport: Literal["stdio", "http", "sse", "streamable-http"] = "stdio"
    default_host: str = "127.0.0.1"
    default_port: int = Field(default=8000, ge=1, le=65535)
    default_path: str | None = None
    http_health_path: str = DEFAULT_HTTP_HEALTH_PATH
    http_ready_path: str = DEFAULT_HTTP_READY_PATH
    allowed_import_roots: list[str] = Field(default_factory=list)
    default_scan_packages: list[str] = Field(default_factory=list)
    import_timeout_seconds: float = Field(
        default=DEFAULT_IMPORT_TIMEOUT_SECONDS,
        ge=0.1,
        le=60.0,
    )
    record_error_history_limit: int = Field(
        default=DEFAULT_ERROR_HISTORY_LIMIT,
        ge=1,
        le=500,
    )
    read_only_mode: bool = True
    network_access_enabled: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            choices = ", ".join(sorted(VALID_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {choices}")
        return normalized

    @field_validator("http_health_path", "http_ready_path")
    @classmethod
    def validate_http_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("HTTP route paths must start with '/'.")
        return value.rstrip("/") or "/"

    @field_validator("allowed_import_roots", "default_scan_packages")
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def validate_routes(self) -> "ServerSettings":
        if self.http_health_path == self.http_ready_path:
            raise ValueError(
                "http_health_path and http_ready_path must be different routes."
            )
        return self


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean value.")


def _env_optional_str(name: str, default: str | None) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip()
    return value or None


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return float(raw_value)


def _env_list(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def load_server_settings() -> ServerSettings:
    payload = {
        "log_level": os.getenv("PYDANTIC_MCP_LOG_LEVEL", DEFAULT_LOG_LEVEL),
        "mask_error_details": _env_bool("PYDANTIC_MCP_MASK_ERROR_DETAILS", True),
        "strict_input_validation": _env_bool(
            "PYDANTIC_MCP_STRICT_INPUT_VALIDATION",
            True,
        ),
        "default_transport": os.getenv("PYDANTIC_MCP_TRANSPORT", "stdio"),
        "default_host": os.getenv("PYDANTIC_MCP_HOST", "127.0.0.1"),
        "default_port": _env_int("PYDANTIC_MCP_PORT", 8000),
        "default_path": _env_optional_str("PYDANTIC_MCP_PATH", None),
        "http_health_path": os.getenv(
            "PYDANTIC_MCP_HTTP_HEALTH_PATH",
            DEFAULT_HTTP_HEALTH_PATH,
        ),
        "http_ready_path": os.getenv(
            "PYDANTIC_MCP_HTTP_READY_PATH",
            DEFAULT_HTTP_READY_PATH,
        ),
        "allowed_import_roots": _env_list("PYDANTIC_MCP_ALLOWED_IMPORT_ROOTS", []),
        "default_scan_packages": _env_list("PYDANTIC_MCP_DEFAULT_SCAN_PACKAGES", []),
        "import_timeout_seconds": _env_float(
            "PYDANTIC_MCP_IMPORT_TIMEOUT_SECONDS",
            DEFAULT_IMPORT_TIMEOUT_SECONDS,
        ),
        "record_error_history_limit": _env_int(
            "PYDANTIC_MCP_ERROR_HISTORY_LIMIT",
            DEFAULT_ERROR_HISTORY_LIMIT,
        ),
        "read_only_mode": _env_bool("PYDANTIC_MCP_READ_ONLY_MODE", True),
        "network_access_enabled": _env_bool(
            "PYDANTIC_MCP_NETWORK_ACCESS_ENABLED",
            False,
        ),
    }
    return ServerSettings.model_validate(payload)
