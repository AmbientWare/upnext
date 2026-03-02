"""Admin routes for user and API key management."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from shared.contracts.admin import (
    AdminApiKeyCreatedResponse,
    AdminApiKeyResponse,
    AdminApiKeysListResponse,
    AdminUserCreatedResponse,
    AdminUserResponse,
    AdminUsersListResponse,
    CreateApiKeyRequest,
    CreateUserRequest,
    ToggleApiKeyRequest,
    UpdateUserRequest,
)

from server.auth import require_admin
from server.backends.service import BackendService
from server.routes.depends import require_backend

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


# ---- Users ----


@router.get("/users", response_model=AdminUsersListResponse)
async def list_users(backend: BackendService = Depends(require_backend)):
    """List all users with their API key counts."""
    async with backend.session() as tx:
        users_with_counts = await tx.auth.list_users()

    users = [
        AdminUserResponse(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            api_key_count=count,
            created_at=user.created_at.isoformat(),
        )
        for user, count in users_with_counts
    ]
    return AdminUsersListResponse(users=users, total=len(users))


@router.post("/users", response_model=AdminUserCreatedResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    backend: BackendService = Depends(require_backend),
):
    """Create a new user with an initial API key (atomic)."""
    async with backend.session() as tx:
        try:
            user = await tx.auth.create_user(body.username, body.is_admin)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        api_key, raw_key = await tx.auth.create_api_key(user.id, "default")

    return AdminUserCreatedResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        api_key_count=1,
        created_at=user.created_at.isoformat(),
        api_key=AdminApiKeyCreatedResponse(
            id=api_key.id,
            user_id=api_key.user_id,
            key_prefix=api_key.key_prefix,
            name=api_key.name,
            is_active=api_key.is_active,
            raw_key=raw_key,
        ),
    )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, backend: BackendService = Depends(require_backend)):
    """Delete a user and all their API keys."""
    async with backend.session() as tx:
        deleted = await tx.auth.delete_user(user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    backend: BackendService = Depends(require_backend),
):
    """Update user properties (e.g., toggle admin)."""
    async with backend.session() as tx:
        user = await tx.auth.update_user(user_id, is_admin=body.is_admin)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await tx.auth.list_api_keys_for_user(user_id)

    return AdminUserResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        api_key_count=len(keys),
        created_at=user.created_at.isoformat(),
    )


# ---- API Keys ----


@router.get("/users/{user_id}/api-keys", response_model=AdminApiKeysListResponse)
async def list_api_keys(
    user_id: str, backend: BackendService = Depends(require_backend)
):
    """List all API keys for a user."""
    async with backend.session() as tx:
        user = await tx.auth.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await tx.auth.list_api_keys_for_user(user_id)

    api_keys = [
        AdminApiKeyResponse(
            id=key.id,
            user_id=key.user_id,
            key_prefix=key.key_prefix,
            name=key.name,
            is_active=key.is_active,
            last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
            created_at=key.created_at.isoformat(),
        )
        for key in keys
    ]
    return AdminApiKeysListResponse(api_keys=api_keys, total=len(api_keys))


@router.post(
    "/users/{user_id}/api-keys",
    response_model=AdminApiKeyCreatedResponse,
    status_code=201,
)
async def create_api_key(
    user_id: str,
    body: CreateApiKeyRequest,
    backend: BackendService = Depends(require_backend),
):
    """Create a new API key for a user. Returns the raw key once."""
    async with backend.session() as tx:
        user = await tx.auth.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        api_key, raw_key = await tx.auth.create_api_key(user_id, body.name)

    return AdminApiKeyCreatedResponse(
        id=api_key.id,
        user_id=api_key.user_id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        raw_key=raw_key,
    )


@router.post(
    "/users/{user_id}/rotate-api-key",
    response_model=AdminApiKeyCreatedResponse,
)
async def rotate_api_key(
    user_id: str,
    backend: BackendService = Depends(require_backend),
):
    """Rotate a user's API key: delete all existing keys and create a new one."""
    async with backend.session() as tx:
        user = await tx.auth.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        api_key, raw_key = await tx.auth.rotate_api_key(user_id)

    return AdminApiKeyCreatedResponse(
        id=api_key.id,
        user_id=api_key.user_id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        raw_key=raw_key,
    )


@router.delete("/users/{user_id}/api-keys/{key_id}", status_code=204)
async def delete_api_key(
    user_id: str,
    key_id: str,
    backend: BackendService = Depends(require_backend),
):
    """Delete/revoke an API key."""
    async with backend.session() as tx:
        user = await tx.auth.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await tx.auth.list_api_keys_for_user(user_id)
        if not any(key.id == key_id for key in keys):
            raise HTTPException(status_code=404, detail="API key not found")
        deleted = await tx.auth.delete_api_key(key_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="API key not found")


@router.patch("/users/{user_id}/api-keys/{key_id}", response_model=AdminApiKeyResponse)
async def toggle_api_key(
    user_id: str,
    key_id: str,
    body: ToggleApiKeyRequest,
    backend: BackendService = Depends(require_backend),
):
    """Toggle an API key's active state."""
    async with backend.session() as tx:
        user = await tx.auth.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await tx.auth.list_api_keys_for_user(user_id)
        if not any(key.id == key_id for key in keys):
            raise HTTPException(status_code=404, detail="API key not found")
        api_key = await tx.auth.toggle_api_key(key_id, body.is_active)
        if api_key is None:
            raise HTTPException(status_code=404, detail="API key not found")

    return AdminApiKeyResponse(
        id=api_key.id,
        user_id=api_key.user_id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        created_at=api_key.created_at.isoformat(),
    )
