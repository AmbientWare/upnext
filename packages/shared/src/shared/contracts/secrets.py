"""Secrets management contract payloads."""

from pydantic import BaseModel, Field


class SecretResponse(BaseModel):
    """Secret as returned by admin list endpoint (key names only, no values)."""

    id: str
    name: str
    keys: list[str]
    created_at: str
    updated_at: str


class SecretDetailResponse(BaseModel):
    """Secret with decrypted values (admin get/create/update)."""

    id: str
    name: str
    data: dict[str, str]
    created_at: str
    updated_at: str


class SecretsListResponse(BaseModel):
    """Secrets list response for admin."""

    secrets: list[SecretResponse]
    total: int


class CreateSecretRequest(BaseModel):
    """Request body to create a secret."""

    name: str = Field(min_length=1, max_length=255)
    data: dict[str, str]


class UpdateSecretRequest(BaseModel):
    """Request body to update a secret."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    data: dict[str, str] | None = None


class SecretValuesResponse(BaseModel):
    """Secret values response for SDK fetch."""

    name: str
    data: dict[str, str]


__all__ = [
    "CreateSecretRequest",
    "SecretDetailResponse",
    "SecretResponse",
    "SecretValuesResponse",
    "SecretsListResponse",
    "UpdateSecretRequest",
]
