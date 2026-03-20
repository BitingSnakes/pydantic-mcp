from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
import importlib
import inspect
import json
import os
import pkgutil
import re
import time
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, get_args, get_origin

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined, from_json

from .constants import PROCESS_STARTED_AT, SERVER_NAME, SERVER_VERSION
from .models import (
    Diagnostic,
    ErrorRecord,
    ExamplePayload,
    FieldContract,
    MigrationFinding,
    ModelSummary,
    ResolvedTarget,
    ServerCapabilities,
    ToolResponse,
    TypeDescription,
    ValidationIssue,
)
from .settings import ServerSettings


@dataclass(slots=True)
class RuntimeTarget:
    raw_target: str
    resolved: ResolvedTarget
    annotation: Any
    adapter: TypeAdapter[Any]
    model_class: type[BaseModel] | None = None


@dataclass(slots=True)
class RegistryEntry:
    name: str
    qualified_name: str
    module: str
    obj: type[BaseModel]
    docstring: str | None
    module_file: str | None
    modified_time: float | None


class RegistryCache:
    def __init__(self, settings: ServerSettings) -> None:
        self.settings = settings
        self._cache: dict[tuple[str, ...], dict[str, RegistryEntry]] = {}

    def clear(self) -> None:
        self._cache.clear()

    def discover(self, packages: Iterable[str]) -> dict[str, RegistryEntry]:
        package_list = tuple(sorted(dict.fromkeys(pkg for pkg in packages if pkg)))
        cached = self._cache.get(package_list)
        if cached is not None:
            return cached

        entries: dict[str, RegistryEntry] = {}
        started = time.monotonic()
        for package_name in package_list:
            self._ensure_allowed_import(package_name)
            module = self._safe_import(package_name)
            self._collect_models_from_module(module, entries)
            if hasattr(module, "__path__"):
                for module_info in pkgutil.walk_packages(
                    module.__path__,
                    prefix=f"{package_name}.",
                ):
                    if (
                        time.monotonic() - started
                        > self.settings.import_timeout_seconds
                    ):
                        raise ToolError(
                            "Model discovery exceeded the configured import timeout."
                        )
                    child_module = self._safe_import(module_info.name)
                    self._collect_models_from_module(child_module, entries)

        self._cache[package_list] = entries
        return entries

    def _ensure_allowed_import(self, module_name: str) -> None:
        if not self.settings.allowed_import_roots:
            return
        if any(
            module_name == root or module_name.startswith(f"{root}.")
            for root in self.settings.allowed_import_roots
        ):
            return
        raise ToolError(
            f"Import path '{module_name}' is outside the configured allowlist."
        )

    def _safe_import(self, module_name: str) -> Any:
        self._ensure_allowed_import(module_name)
        try:
            return importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Failed to import '{module_name}': {exc}") from exc

    def _collect_models_from_module(
        self,
        module: Any,
        entries: dict[str, RegistryEntry],
    ) -> None:
        module_file = getattr(module, "__file__", None)

        for attr_name in dir(module):
            try:
                value = getattr(module, attr_name)
            except Exception:  # noqa: BLE001
                continue
            if (
                inspect.isclass(value)
                and issubclass(value, BaseModel)
                and value is not BaseModel
                and value.__module__ == module.__name__
            ):
                qualified_name = f"{value.__module__}.{value.__name__}"
                entries[qualified_name] = RegistryEntry(
                    name=value.__name__,
                    qualified_name=qualified_name,
                    module=value.__module__,
                    obj=value,
                    docstring=inspect.getdoc(value),
                    module_file=module_file,
                    modified_time=_safe_mtime(module_file),
                )


def _safe_mtime(path: str | None) -> float | None:
    if not path:
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


class ErrorHistory:
    def __init__(self, limit: int) -> None:
        self._records: deque[ErrorRecord] = deque(maxlen=limit)

    def add(self, record: ErrorRecord) -> None:
        self._records.appendleft(record)

    def list(self) -> list[ErrorRecord]:
        return list(self._records)


MIGRATION_RULES = [
    (
        "parse_obj(",
        "model_validate(",
        "medium",
        "Replace `parse_obj` with `model_validate`.",
    ),
    (
        "parse_raw(",
        "model_validate_json(",
        "high",
        "Replace `parse_raw` with `model_validate_json`.",
    ),
    (
        ".dict(",
        ".model_dump(",
        "medium",
        "Replace `.dict()` with `.model_dump()`.",
    ),
    (
        ".json(",
        ".model_dump_json(",
        "medium",
        "Replace `.json()` with `.model_dump_json()`.",
    ),
    (
        ".schema(",
        ".model_json_schema(",
        "medium",
        "Replace `.schema()` with `.model_json_schema()`.",
    ),
    (
        ".copy(",
        ".model_copy(",
        "low",
        "Replace `.copy()` with `.model_copy()`.",
    ),
    (
        "from_orm",
        "model_validate(..., from_attributes=True)",
        "high",
        "ORM mode moved to `from_attributes=True` plus `model_validate`.",
    ),
    (
        "class Config",
        "model_config = ConfigDict(...)",
        "high",
        "Config subclasses should become `model_config` declarations.",
    ),
]


def build_capabilities(settings: ServerSettings) -> ServerCapabilities:
    return ServerCapabilities(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        allowed_import_roots=settings.allowed_import_roots,
        default_scan_packages=settings.default_scan_packages,
        read_only_mode=settings.read_only_mode,
        network_access_enabled=settings.network_access_enabled,
        import_timeout_seconds=settings.import_timeout_seconds,
        error_history_limit=settings.record_error_history_limit,
    )


def build_health_payload() -> dict[str, Any]:
    now = datetime_utc()
    return {
        "status": "ok",
        "ready": True,
        "checked_at": now,
        "process_started_at": PROCESS_STARTED_AT.isoformat(),
        "uptime_seconds": round(
            (time.time() - PROCESS_STARTED_AT.timestamp()),
            3,
        ),
    }


def datetime_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def registry_entries_to_summaries(
    entries: dict[str, RegistryEntry],
    pattern: str | None = None,
) -> list[ModelSummary]:
    summaries = []
    for entry in entries.values():
        if pattern and not (
            fnmatch(entry.qualified_name, pattern) or fnmatch(entry.name, pattern)
        ):
            continue
        summaries.append(
            ModelSummary(
                name=entry.name,
                qualified_name=entry.qualified_name,
                module=entry.module,
                docstring=entry.docstring,
            )
        )
    return sorted(summaries, key=lambda item: item.qualified_name)


def build_eval_namespace(entries: dict[str, RegistryEntry]) -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "Any": Any,
        "Annotated": Annotated,
        "BaseModel": BaseModel,
        "Literal": Literal,
        "NoneType": NoneType,
        "bool": bool,
        "bytes": bytes,
        "dict": dict,
        "float": float,
        "frozenset": frozenset,
        "int": int,
        "list": list,
        "object": object,
        "set": set,
        "str": str,
        "tuple": tuple,
    }
    namespace.update(vars(importlib.import_module("typing")))
    for root_name in {
        entry.module.split(".", 1)[0] for entry in entries.values() if entry.module
    }:
        namespace[root_name] = importlib.import_module(root_name)
    for entry in entries.values():
        namespace[entry.name] = entry.obj
    return namespace


def resolve_target(
    target: str,
    *,
    registry: RegistryCache,
    settings: ServerSettings,
    packages: Iterable[str] | None = None,
) -> RuntimeTarget:
    package_list = list(packages or settings.default_scan_packages)
    discovered = registry.discover(package_list) if package_list else {}
    namespace = build_eval_namespace(discovered)

    if "\n" in target or target.strip().startswith("class "):
        return _resolve_inline_code(target, namespace)

    if target in discovered:
        entry = discovered[target]
        return _runtime_target_for_model(target, entry.obj)

    matches = [entry for entry in discovered.values() if entry.name == target]
    if len(matches) == 1:
        entry = matches[0]
        return _runtime_target_for_model(target, entry.obj)
    if len(matches) > 1:
        raise ToolError(
            f"Model name '{target}' is ambiguous. Use a qualified import path instead."
        )

    maybe_model = _try_resolve_import_path(target, registry)
    if maybe_model is not None:
        return maybe_model

    for dotted_name in re.findall(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b", target):
        root_name = dotted_name.split(".", 1)[0]
        if root_name in namespace:
            continue
        try:
            namespace[root_name] = importlib.import_module(root_name)
        except Exception:  # noqa: BLE001
            continue

    try:
        annotation = eval(target, {"__builtins__": {}}, namespace)  # noqa: S307
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Could not resolve target '{target}': {exc}") from exc
    return _runtime_target_for_annotation(target, annotation)


def _resolve_inline_code(target: str, namespace: dict[str, Any]) -> RuntimeTarget:
    local_ns = dict(namespace)
    exec(target, {"__builtins__": {}}, local_ns)  # noqa: S102
    candidates = [
        value
        for key, value in local_ns.items()
        if key not in namespace
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value is not BaseModel
    ]
    if len(candidates) != 1:
        raise ToolError(
            "Inline code targets must define exactly one Pydantic BaseModel subclass."
        )
    model_class = candidates[0]
    return RuntimeTarget(
        raw_target=target,
        resolved=ResolvedTarget(
            kind="inline_code",
            target=target,
            qualified_name=f"{model_class.__module__}.{model_class.__name__}",
            module=model_class.__module__,
            display_name=model_class.__name__,
            is_base_model=True,
        ),
        annotation=model_class,
        adapter=TypeAdapter(model_class),
        model_class=model_class,
    )


def _try_resolve_import_path(
    target: str,
    registry: RegistryCache,
) -> RuntimeTarget | None:
    parts = target.split(".")
    for index in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:index])
        attr_path = parts[index:]
        try:
            module = registry._safe_import(module_name)
        except ToolError:
            continue
        value: Any = module
        try:
            for attr in attr_path:
                value = getattr(value, attr)
        except AttributeError:
            continue
        if (
            inspect.isclass(value)
            and issubclass(value, BaseModel)
            and value is not BaseModel
        ):
            return _runtime_target_for_model(target, value)
        return _runtime_target_for_annotation(target, value)
    return None


def _runtime_target_for_model(
    target: str, model_class: type[BaseModel]
) -> RuntimeTarget:
    return RuntimeTarget(
        raw_target=target,
        resolved=ResolvedTarget(
            kind="model",
            target=target,
            qualified_name=f"{model_class.__module__}.{model_class.__name__}",
            module=model_class.__module__,
            display_name=model_class.__name__,
            is_base_model=True,
        ),
        annotation=model_class,
        adapter=TypeAdapter(model_class),
        model_class=model_class,
    )


def _runtime_target_for_annotation(target: str, annotation: Any) -> RuntimeTarget:
    display_name = getattr(annotation, "__name__", repr(annotation))
    return RuntimeTarget(
        raw_target=target,
        resolved=ResolvedTarget(
            kind="type_expression",
            target=target,
            qualified_name=None,
            module=getattr(annotation, "__module__", None),
            display_name=display_name,
            is_base_model=inspect.isclass(annotation)
            and issubclass(annotation, BaseModel)
            and annotation is not BaseModel,
        ),
        annotation=annotation,
        adapter=TypeAdapter(annotation),
        model_class=annotation
        if inspect.isclass(annotation)
        and issubclass(annotation, BaseModel)
        and annotation is not BaseModel
        else None,
    )


def normalize_validation_error(error: ValidationError) -> list[ValidationIssue]:
    issues = []
    for item in error.errors(include_url=False):
        location = [str(part) for part in item.get("loc", ())]
        error_type = str(item.get("type", "validation_error"))
        message = str(item.get("msg", "Validation error"))
        offending_input = item.get("input")
        issues.append(
            ValidationIssue(
                location=location,
                error_type=error_type,
                message=message,
                offending_input=offending_input,
                suggested_repair=_suggest_repair(error_type),
            )
        )
    return issues


def _suggest_repair(error_type: str) -> str | None:
    if "missing" in error_type:
        return "Add the missing required field."
    if "int" in error_type:
        return "Provide an integer-compatible value."
    if "string" in error_type:
        return "Provide a string value."
    if "list" in error_type:
        return "Provide an array/list value."
    if "dict" in error_type or "mapping" in error_type:
        return "Provide an object/dictionary value."
    return None


def describe_type(annotation: Any, *, expand_nested: bool = True) -> TypeDescription:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        return TypeDescription(display="Any", category="any")
    if annotation in {str, int, float, bool, bytes}:
        return TypeDescription(display=annotation.__name__, category="scalar")
    if annotation is NoneType:
        return TypeDescription(display="None", category="none", nullable=True)
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return TypeDescription(
            display=annotation.__name__,
            category="model",
            origin=f"{annotation.__module__}.{annotation.__name__}",
        )
    if origin in {list, set, tuple, frozenset}:
        return TypeDescription(
            display=repr(annotation),
            category="collection",
            origin=getattr(origin, "__name__", repr(origin)),
            args=[
                describe_type(arg, expand_nested=expand_nested)
                for arg in (args if expand_nested else ())
            ],
        )
    if origin in {dict}:
        return TypeDescription(
            display=repr(annotation),
            category="mapping",
            origin="dict",
            args=[
                describe_type(arg, expand_nested=expand_nested)
                for arg in (args if expand_nested else ())
            ],
        )
    if origin in {Literal}:
        return TypeDescription(
            display=repr(annotation),
            category="literal",
            literals=list(args),
        )
    if origin in {Annotated}:
        base, *metadata = args
        description = describe_type(base, expand_nested=expand_nested)
        description.annotated_metadata = [repr(item) for item in metadata]
        description.is_strict = any("Strict" in repr(item) for item in metadata)
        return description
    if origin in {
        UnionType,
        getattr(importlib.import_module("typing"), "Union", object()),
    }:
        nullable = NoneType in args
        members = [arg for arg in args if arg is not NoneType]
        return TypeDescription(
            display=repr(annotation),
            category="union",
            union_members=[
                describe_type(member, expand_nested=expand_nested)
                for member in (members if expand_nested else ())
            ],
            nullable=nullable,
        )
    return TypeDescription(
        display=repr(annotation),
        category="unknown",
        origin=getattr(origin, "__name__", None) if origin else None,
    )


def field_contracts_for_model(model_class: type[BaseModel]) -> list[FieldContract]:
    contracts = []
    for name, field in model_class.model_fields.items():
        contracts.append(
            FieldContract(
                name=name,
                annotation=repr(field.annotation),
                required=field.is_required(),
                default=None if field.default is PydanticUndefined else field.default,
                alias=field.alias,
                description=field.description,
                constraints=field_constraints(field),
            )
        )
    return contracts


def field_constraints(field: FieldInfo) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for key in (
        "min_length",
        "max_length",
        "pattern",
        "gt",
        "ge",
        "lt",
        "le",
        "multiple_of",
    ):
        value = getattr(field, key, None)
        if value is not None:
            constraints[key] = value
    for item in getattr(field, "metadata", ()):
        class_name = item.__class__.__name__.lower()
        if hasattr(item, "ge"):
            constraints["ge"] = getattr(item, "ge")
        if hasattr(item, "gt"):
            constraints["gt"] = getattr(item, "gt")
        if hasattr(item, "le"):
            constraints["le"] = getattr(item, "le")
        if hasattr(item, "lt"):
            constraints["lt"] = getattr(item, "lt")
        if hasattr(item, "min_length"):
            constraints["min_length"] = getattr(item, "min_length")
        if hasattr(item, "max_length"):
            constraints["max_length"] = getattr(item, "max_length")
        if hasattr(item, "pattern"):
            constraints["pattern"] = getattr(item, "pattern")
        if class_name == "ge":
            constraints["ge"] = getattr(item, "ge", None)
        if class_name == "le":
            constraints["le"] = getattr(item, "le", None)
    return constraints


def explain_model_data(
    runtime_target: RuntimeTarget,
    *,
    include_constraints: bool,
    include_defaults: bool,
) -> dict[str, Any]:
    if runtime_target.model_class is None:
        description = describe_type(runtime_target.annotation)
        return {
            "summary": f"{runtime_target.resolved.display_name} is a type expression, not a BaseModel.",
            "type": description.model_dump(mode="json"),
        }

    decorators = runtime_target.model_class.__pydantic_decorators__
    fields = []
    for contract in field_contracts_for_model(runtime_target.model_class):
        payload = contract.model_dump(mode="json")
        if not include_constraints:
            payload["constraints"] = {}
        if not include_defaults:
            payload["default"] = None
        fields.append(payload)

    return {
        "summary": inspect.getdoc(runtime_target.model_class),
        "fields": fields,
        "required_fields": [
            contract.name
            for contract in field_contracts_for_model(runtime_target.model_class)
            if contract.required
        ],
        "optional_fields": [
            contract.name
            for contract in field_contracts_for_model(runtime_target.model_class)
            if not contract.required
        ],
        "aliases": {
            contract.name: contract.alias
            for contract in field_contracts_for_model(runtime_target.model_class)
            if contract.alias
        },
        "decorators": {
            "field_validators": sorted(decorators.field_validators.keys()),
            "model_validators": sorted(decorators.model_validators.keys()),
            "field_serializers": sorted(decorators.field_serializers.keys()),
            "model_serializers": sorted(decorators.model_serializers.keys()),
            "computed_fields": sorted(decorators.computed_fields.keys()),
        },
        "nested_models": sorted(
            {
                description.origin
                for description in (
                    describe_type(field.annotation)
                    for field in runtime_target.model_class.model_fields.values()
                )
                if description.origin and description.category == "model"
            }
        ),
    }


def validate_with_adapter(
    runtime_target: RuntimeTarget,
    *,
    data: Any,
    mode: str,
    strict: bool,
    context: dict[str, Any] | None,
) -> ToolResponse:
    diagnostics: list[Diagnostic] = []
    try:
        if mode == "json":
            raw_json = data if isinstance(data, str) else json.dumps(data)
            validated = runtime_target.adapter.validate_json(
                raw_json,
                strict=strict,
                context=context,
            )
        else:
            validated = runtime_target.adapter.validate_python(
                data,
                strict=strict,
                context=context,
            )
    except ValidationError as exc:
        issues = normalize_validation_error(exc)
        diagnostics.append(
            Diagnostic(
                level="error",
                message="Validation failed.",
                code="validation_error",
                context={"issue_count": len(issues)},
            )
        )
        return ToolResponse(
            resolved_target=runtime_target.resolved,
            diagnostics=diagnostics,
            result={
                "ok": False,
                "data": None,
                "errors": [issue.model_dump(mode="json") for issue in issues],
                "warnings": [],
            },
        )

    warnings = validation_warnings(runtime_target, data, validated, strict=strict)
    for warning in warnings:
        diagnostics.append(
            Diagnostic(level="warning", message=warning, code="validation_warning")
        )

    return ToolResponse(
        resolved_target=runtime_target.resolved,
        diagnostics=diagnostics,
        result={
            "ok": True,
            "data": to_jsonable(validated),
            "errors": [],
            "warnings": warnings,
        },
    )


def validation_warnings(
    runtime_target: RuntimeTarget,
    original: Any,
    validated: Any,
    *,
    strict: bool,
) -> list[str]:
    warnings: list[str] = []
    original_json = _safe_json_dump(original)
    validated_json = _safe_json_dump(to_jsonable(validated))
    if not strict and original_json is not None and validated_json is not None:
        if original_json != validated_json:
            warnings.append(
                "Validation coerced or normalized the input compared with the original payload."
            )
    if runtime_target.model_class and isinstance(original, dict):
        ignored_fields = sorted(
            key
            for key in original
            if key not in runtime_target.model_class.model_fields
            and key
            not in {
                field.alias
                for field in runtime_target.model_class.model_fields.values()
                if field.alias
            }
        )
        if ignored_fields:
            warnings.append(f"Ignored extra fields: {', '.join(ignored_fields)}")
    return warnings


def serialize_with_adapter(
    runtime_target: RuntimeTarget,
    *,
    data: Any,
    output_mode: str,
    by_alias: bool,
    exclude_unset: bool,
    exclude_defaults: bool,
    exclude_none: bool,
    round_trip: bool,
) -> ToolResponse:
    validation = validate_with_adapter(
        runtime_target,
        data=data,
        mode="python",
        strict=False,
        context=None,
    )
    if not validation.result.get("ok"):
        return validation

    validated_data = runtime_target.adapter.validate_python(data)
    if output_mode == "json":
        dumped_json = runtime_target.adapter.dump_json(
            validated_data,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
        )
        serialized = json.loads(dumped_json.decode("utf-8"))
        notes = []
        if isinstance(validated_data, bytes):
            notes.append("Binary data was converted to JSON-safe output.")
    else:
        serialized = runtime_target.adapter.dump_python(
            validated_data,
            mode="python",
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
        )
        notes = []

    return ToolResponse(
        resolved_target=runtime_target.resolved,
        diagnostics=validation.diagnostics,
        result={
            "ok": True,
            "data": to_jsonable(serialized),
            "notes": notes,
        },
    )


def build_schema_report(
    runtime_target: RuntimeTarget,
    *,
    schema_mode: str,
    include_definitions: bool,
) -> ToolResponse:
    schema = runtime_target.adapter.json_schema(mode=schema_mode)
    field_summaries: list[dict[str, Any]] = []
    if runtime_target.model_class is not None:
        for contract in field_contracts_for_model(runtime_target.model_class):
            field_summaries.append(
                {
                    "name": contract.name,
                    "required": contract.required,
                    "constraints": contract.constraints,
                    "alias": contract.alias,
                }
            )

    defs = schema.get("$defs", {})
    if not include_definitions and "$defs" in schema:
        schema = {key: value for key, value in schema.items() if key != "$defs"}

    return ToolResponse(
        resolved_target=runtime_target.resolved,
        artifacts={"schema_mode": schema_mode},
        result={
            "schema": schema,
            "definitions": defs if include_definitions else {},
            "field_constraints": field_summaries,
        },
    )


def create_examples(
    runtime_target: RuntimeTarget, *, count: int, invalid: bool
) -> list[ExamplePayload]:
    examples = []
    for index in range(count):
        valid_payload = example_for_annotation(runtime_target.annotation, seed=index)
        examples.append(
            ExamplePayload(
                kind="valid",
                payload=valid_payload,
                rationale="Generated to satisfy the resolved type contract.",
            )
        )
        if invalid:
            invalid_payload = invalid_example_for_annotation(
                runtime_target.annotation,
                seed=index,
            )
            examples.append(
                ExamplePayload(
                    kind="invalid",
                    payload=invalid_payload,
                    rationale="Generated to violate the resolved type contract.",
                )
            )
    return examples


def example_for_annotation(annotation: Any, *, seed: int = 0) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        payload = {}
        for name, field in annotation.model_fields.items():
            if field.default is not PydanticUndefined:
                payload[name] = field.default
            elif field.default_factory is not None:
                payload[name] = field.default_factory()
            else:
                payload[name] = example_for_annotation(field.annotation, seed=seed + 1)
        return payload
    if annotation is str:
        return f"example-{seed}"
    if annotation is int:
        return seed + 1
    if annotation is float:
        return float(seed + 1.5)
    if annotation is bool:
        return seed % 2 == 0
    if annotation is bytes:
        return "ZXhhbXBsZQ=="
    if origin in {list, set, tuple, frozenset} and args:
        item = example_for_annotation(args[0], seed=seed + 1)
        return [item]
    if origin is dict and len(args) == 2:
        return {f"key-{seed}": example_for_annotation(args[1], seed=seed + 1)}
    if origin in {Literal} and args:
        return args[0]
    if origin in {Annotated} and args:
        return example_for_annotation(args[0], seed=seed)
    if (
        origin
        in {UnionType, getattr(importlib.import_module("typing"), "Union", object())}
        and args
    ):
        for arg in args:
            if arg is not NoneType:
                return example_for_annotation(arg, seed=seed)
    return {"value": f"example-{seed}"}


def invalid_example_for_annotation(annotation: Any, *, seed: int = 0) -> Any:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        required_fields = [
            name
            for name, field in annotation.model_fields.items()
            if field.is_required()
        ]
        payload = example_for_annotation(annotation, seed=seed)
        if required_fields and isinstance(payload, dict):
            payload.pop(required_fields[0], None)
            return payload
        return {"unexpected": object()}
    if annotation in {str, int, float, bool}:
        return {"wrong": "type"}
    return None


def compare_validation_modes(
    runtime_target: RuntimeTarget, *, data: Any
) -> ToolResponse:
    raw_json = json.dumps(data)
    adapters = [("type_adapter", runtime_target.adapter)]
    if runtime_target.model_class is not None:
        adapters.append(("model", TypeAdapter(runtime_target.model_class)))
    comparisons = []
    for adapter_kind, adapter in adapters:
        for strict in (False, True):
            for mode, payload in (("python", data), ("json", raw_json)):
                try:
                    if mode == "python":
                        value = adapter.validate_python(payload, strict=strict)
                    else:
                        value = adapter.validate_json(payload, strict=strict)
                    comparisons.append(
                        {
                            "adapter": adapter_kind,
                            "mode": mode,
                            "strict": strict,
                            "ok": True,
                            "value": to_jsonable(value),
                        }
                    )
                except ValidationError as exc:
                    comparisons.append(
                        {
                            "adapter": adapter_kind,
                            "mode": mode,
                            "strict": strict,
                            "ok": False,
                            "errors": [
                                issue.model_dump(mode="json")
                                for issue in normalize_validation_error(exc)
                            ],
                        }
                    )
    validation_schema = runtime_target.adapter.json_schema(mode="validation")
    serialization_schema = runtime_target.adapter.json_schema(mode="serialization")
    return ToolResponse(
        resolved_target=runtime_target.resolved,
        result={
            "comparisons": comparisons,
            "schema_difference": {
                "validation_keys": sorted(validation_schema.keys()),
                "serialization_keys": sorted(serialization_schema.keys()),
                "schemas_equal": validation_schema == serialization_schema,
            },
        },
    )


def migration_report(code: str, *, apply_fixes: bool) -> ToolResponse:
    findings = []
    updated_code = code
    for legacy, replacement, severity, message in MIGRATION_RULES:
        if legacy in updated_code:
            findings.append(
                MigrationFinding(
                    severity=severity,  # type: ignore[arg-type]
                    legacy_pattern=legacy,
                    replacement=replacement,
                    message=message,
                )
            )
            if apply_fixes:
                updated_code = updated_code.replace(legacy, replacement)
    return ToolResponse(
        diagnostics=[
            Diagnostic(
                level="warning" if findings else "info",
                message="Migration analysis completed.",
                code="migration_analysis",
                context={"finding_count": len(findings)},
            )
        ],
        result={
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "risk_level": highest_risk(findings),
            "updated_code": updated_code if apply_fixes else None,
        },
    )


def highest_risk(findings: list[MigrationFinding]) -> str:
    if any(finding.severity == "high" for finding in findings):
        return "high"
    if any(finding.severity == "medium" for finding in findings):
        return "medium"
    if findings:
        return "low"
    return "none"


def parse_partial_json_report(
    runtime_target: RuntimeTarget,
    *,
    partial_json: str,
    allow_partial: bool,
) -> ToolResponse:
    try:
        parsed = from_json(partial_json, allow_partial=allow_partial)
    except ValueError as exc:
        return ToolResponse(
            resolved_target=runtime_target.resolved,
            diagnostics=[
                Diagnostic(level="error", message=str(exc), code="partial_json_error")
            ],
            result={
                "parsed_fragment": None,
                "validation": {"ok": False, "errors": []},
                "stopped_at": len(partial_json),
            },
        )

    validation = validate_with_adapter(
        runtime_target,
        data=parsed,
        mode="python",
        strict=False,
        context=None,
    )
    consumed = _approximate_json_consumed_length(partial_json)
    return ToolResponse(
        resolved_target=runtime_target.resolved,
        diagnostics=validation.diagnostics,
        result={
            "parsed_fragment": to_jsonable(parsed),
            "validation": validation.result,
            "stopped_at": consumed,
        },
    )


def _approximate_json_consumed_length(value: str) -> int:
    trimmed = value.rstrip()
    for index, char in enumerate(trimmed):
        if char in ",]}":
            return index
    return len(trimmed)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


def _safe_json_dump(value: Any) -> str | None:
    try:
        return json.dumps(value, sort_keys=True, default=repr)
    except TypeError:
        return None


def make_response(
    *,
    resolved_target: ResolvedTarget | None = None,
    diagnostics: list[Diagnostic] | None = None,
    artifacts: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> ToolResponse:
    return ToolResponse(
        resolved_target=resolved_target,
        diagnostics=diagnostics or [],
        artifacts=artifacts or {},
        result=result or {},
    )
