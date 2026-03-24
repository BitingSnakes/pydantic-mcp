from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Address(BaseModel):
    street: str
    city: str
    postal_code: Annotated[str, Field(min_length=5, max_length=10)]


class UserCreate(BaseModel):
    """Payload for creating a user."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    email: EmailStr = Field(alias="emailAddress")
    age: Annotated[int, Field(ge=0, le=130)]
    tags: list[str] = Field(default_factory=list)
    address: Address | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return [item.strip().lower() for item in value]
