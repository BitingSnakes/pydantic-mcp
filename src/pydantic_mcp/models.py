from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Diagnostic(BaseModel):
    level: Literal["info", "warning", "error"] = "info"
    message: str
    code: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ResolvedTarget(BaseModel):
    kind: Literal["model", "type_expression", "inline_code"]
    target: str
    qualified_name: str | None = None
    module: str | None = None
    display_name: str
    is_base_model: bool


class ModelSummary(BaseModel):
    name: str
    qualified_name: str
    module: str
    docstring: str | None = None


class TypeDescription(BaseModel):
    display: str
    category: str
    origin: str | None = None
    args: list["TypeDescription"] = Field(default_factory=list)
    union_members: list["TypeDescription"] = Field(default_factory=list)
    literals: list[Any] = Field(default_factory=list)
    annotated_metadata: list[str] = Field(default_factory=list)
    nullable: bool = False
    is_strict: bool = False
    constraints: dict[str, Any] = Field(default_factory=dict)


class FieldContract(BaseModel):
    name: str
    annotation: str
    required: bool
    default: Any = None
    alias: str | None = None
    description: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    location: list[str]
    error_type: str
    message: str
    offending_input: Any = None
    suggested_repair: str | None = None


class ExamplePayload(BaseModel):
    kind: Literal["valid", "invalid"]
    payload: Any
    rationale: str


class MigrationFinding(BaseModel):
    severity: Literal["low", "medium", "high"]
    legacy_pattern: str
    replacement: str
    message: str


class ErrorRecord(BaseModel):
    tool_name: str
    target: str | None = None
    message: str
    issues: list[ValidationIssue] = Field(default_factory=list)


class ToolResponse(BaseModel):
    resolved_target: ResolvedTarget | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class ServerCapabilities(BaseModel):
    server_name: str
    server_version: str
    allowed_import_roots: list[str] = Field(default_factory=list)
    default_scan_packages: list[str] = Field(default_factory=list)
    read_only_mode: bool
    network_access_enabled: bool
    import_timeout_seconds: float
    error_history_limit: int
