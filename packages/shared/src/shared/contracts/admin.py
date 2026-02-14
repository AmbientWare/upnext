"""Admin API contract payloads."""

from pydantic import BaseModel, Field


class AdminApiKeyResponse(BaseModel):
    """API key as returned by admin endpoints (never includes raw key)."""

    id: str
    user_id: str
    key_prefix: str
    name: str
    is_active: bool
    last_used_at: str | None = None
    created_at: str


class AdminApiKeyCreatedResponse(BaseModel):
    """Response when creating a new API key (includes raw key once)."""

    id: str
    user_id: str
    key_prefix: str
    name: str
    is_active: bool
    raw_key: str


class AdminUserResponse(BaseModel):
    """User as returned by admin endpoints."""

    id: str
    username: str
    is_admin: bool
    api_key_count: int = 0
    created_at: str


class AdminUserCreatedResponse(BaseModel):
    """Response when creating a user (includes initial API key)."""

    id: str
    username: str
    is_admin: bool
    api_key_count: int = 1
    created_at: str
    api_key: AdminApiKeyCreatedResponse


class AdminUsersListResponse(BaseModel):
    """Users list response for admin."""

    users: list[AdminUserResponse]
    total: int


class AdminApiKeysListResponse(BaseModel):
    """API keys list response for a specific user."""

    api_keys: list[AdminApiKeyResponse]
    total: int


class CreateUserRequest(BaseModel):
    """Request body to create a user."""

    username: str = Field(min_length=1, max_length=255)
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    """Request body to update a user."""

    is_admin: bool | None = None


class CreateApiKeyRequest(BaseModel):
    """Request body to create an API key for a user."""

    name: str = Field(default="default", min_length=1, max_length=255)


class ToggleApiKeyRequest(BaseModel):
    """Request body to toggle an API key's active state."""

    is_active: bool


__all__ = [
    "AdminApiKeyCreatedResponse",
    "AdminApiKeyResponse",
    "AdminApiKeysListResponse",
    "AdminUserCreatedResponse",
    "AdminUserResponse",
    "AdminUsersListResponse",
    "CreateApiKeyRequest",
    "CreateUserRequest",
    "ToggleApiKeyRequest",
    "UpdateUserRequest",
]
