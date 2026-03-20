from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server import (
    compare_validation_modes,
    create_example_payload,
    explain_model,
    generate_model_from_json,
    generate_json_schema,
    inspect_type,
    list_models,
    migrate_v1_to_v2,
    parse_partial_json,
    serialize_data,
    validate_data,
)


TARGET = "tests.fixtures.sample_app.models.UserCreate"


def test_list_models_discovers_fixture_package() -> None:
    result = list_models(packages=["tests.fixtures.sample_app"])

    qualified_names = [item["qualified_name"] for item in result.result["models"]]

    assert "tests.fixtures.sample_app.models.UserCreate" in qualified_names
    assert "tests.fixtures.sample_app.models.Address" in qualified_names


def test_validate_data_returns_normalized_payload_and_warnings() -> None:
    result = validate_data(
        target=TARGET,
        data={
            "email": "alice@example.com",
            "age": "20",
            "tags": ["vip"],
            "extra_field": "ignored",
        },
    )

    assert result.result["ok"] is True
    assert result.result["data"]["age"] == 20
    assert any(
        "Ignored extra fields" in warning for warning in result.result["warnings"]
    )


def test_serialize_data_supports_alias_and_json_mode() -> None:
    result = serialize_data(
        target=TARGET,
        data={
            "email": "alice@example.com",
            "age": 20,
            "tags": ["vip"],
        },
        output_mode="json",
        by_alias=True,
    )

    assert result.result["ok"] is True
    assert result.result["data"]["emailAddress"] == "alice@example.com"


def test_generate_json_schema_returns_field_constraints() -> None:
    result = generate_json_schema(target=TARGET, schema_mode="validation")

    assert result.result["schema"]["type"] == "object"
    assert any(
        item["name"] == "age" and item["constraints"]["ge"] == 0
        for item in result.result["field_constraints"]
    )


def test_explain_model_includes_examples_and_decorators() -> None:
    result = explain_model(target=TARGET)

    assert "fields" in result.result
    assert result.result["examples"]
    assert "field_validators" in result.result["decorators"]


def test_inspect_type_handles_type_expression() -> None:
    result = inspect_type(
        target="list[tests.fixtures.sample_app.models.UserCreate]",
    )

    assert result.result["type"]["category"] == "collection"
    assert result.result["type"]["args"][0]["category"] == "model"


def test_inspect_type_handles_object_builtin_in_type_expression() -> None:
    result = inspect_type(target="dict[str, object]")

    assert result.result["type"]["category"] == "mapping"
    assert result.result["type"]["args"][0]["category"] == "scalar"
    assert result.result["type"]["args"][0]["display"] == "str"
    assert result.result["type"]["args"][1]["display"] == "<class 'object'>"


def test_create_example_payload_emits_valid_and_invalid_examples() -> None:
    result = create_example_payload(target=TARGET, count=1, invalid_examples=True)

    kinds = [item["kind"] for item in result.result["examples"]]
    assert kinds == ["valid", "invalid"]


def test_generate_model_from_json_builds_nested_models() -> None:
    result = generate_model_from_json(
        model_name="OrderPayload",
        json_input={
            "order_id": 123,
            "customer": {"name": "Alice", "vip": True},
            "items": [
                {"sku": "A-1", "quantity": 2},
                {"sku": "B-2"},
            ],
            "shipping-address": {"city": "San Francisco"},
        },
    )

    assert result.result["ok"] is True
    assert "class OrderPayloadCustomer(BaseModel):" in result.result["code"]
    assert "class OrderPayloadItemsItem(BaseModel):" in result.result["code"]
    assert (
        "shipping_address: OrderPayloadShippingAddress = Field(alias='shipping-address')"
        in result.result["code"]
    )
    assert "quantity: int | None = None" in result.result["code"]
    namespace: dict[str, object] = {}
    exec(result.result["code"], namespace)
    assert "OrderPayload" in namespace


def test_compare_validation_modes_reports_matrix() -> None:
    result = compare_validation_modes(
        target="list[int]",
        data=["1", 2],
    )

    assert len(result.result["comparisons"]) == 4
    assert any(
        item["ok"] is False for item in result.result["comparisons"] if item["strict"]
    )


def test_migrate_v1_to_v2_finds_common_legacy_patterns() -> None:
    code = """
from pydantic import BaseModel

class User(BaseModel):
    name: str

payload = User.parse_obj({"name": "Alice"})
as_dict = payload.dict()
"""
    result = migrate_v1_to_v2(code=code, apply_fixes=True)

    assert result.result["risk_level"] in {"medium", "high"}
    assert "model_validate" in result.result["updated_code"]
    assert "model_dump" in result.result["updated_code"]


def test_parse_partial_json_best_effort_parses_fragment() -> None:
    result = parse_partial_json(
        target="list[int]",
        partial_json="[1, 2,",
        allow_partial=True,
    )

    assert result.result["parsed_fragment"] == [1, 2]
    assert result.result["validation"]["ok"] is True
