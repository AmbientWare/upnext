"""Admin routes for user and API key management."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from server.db.repositories import AuthRepository
from server.db.session import Database
from server.routes.depends import require_database
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- Users ----


@router.get("/users", response_model=AdminUsersListResponse)
async def list_users(db: Database = Depends(require_database)):
    """List all users with their API key counts."""
    async with db.session() as session:
        repo = AuthRepository(session)
        users_with_counts = await repo.list_users()

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
    db: Database = Depends(require_database),
):
    """Create a new user with an initial API key (atomic)."""
    async with db.session() as session:
        repo = AuthRepository(session)
        try:
            user = await repo.create_user(body.username, body.is_admin)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        api_key, raw_key = await repo.create_api_key(user.id, "default")

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
async def delete_user(user_id: str, db: Database = Depends(require_database)):
    """Delete a user and all their API keys."""
    async with db.session() as session:
        repo = AuthRepository(session)
        deleted = await repo.delete_user(user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    db: Database = Depends(require_database),
):
    """Update user properties (e.g., toggle admin)."""
    async with db.session() as session:
        repo = AuthRepository(session)
        user = await repo.update_user(user_id, is_admin=body.is_admin)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await repo.list_api_keys_for_user(user_id)

    return AdminUserResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        api_key_count=len(keys),
        created_at=user.created_at.isoformat(),
    )


# ---- API Keys ----


@router.get("/users/{user_id}/api-keys", response_model=AdminApiKeysListResponse)
async def list_api_keys(user_id: str, db: Database = Depends(require_database)):
    """List all API keys for a user."""
    async with db.session() as session:
        repo = AuthRepository(session)
        user = await repo.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        keys = await repo.list_api_keys_for_user(user_id)

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
    db: Database = Depends(require_database),
):
    """Create a new API key for a user. Returns the raw key once."""
    async with db.session() as session:
        repo = AuthRepository(session)
        user = await repo.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        api_key, raw_key = await repo.create_api_key(user_id, body.name)

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
    db: Database = Depends(require_database),
):
    """Rotate a user's API key: delete all existing keys and create a new one."""
    async with db.session() as session:
        repo = AuthRepository(session)
        user = await repo.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        api_key, raw_key = await repo.rotate_api_key(user_id)

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
    db: Database = Depends(require_database),
):
    """Delete/revoke an API key."""
    async with db.session() as session:
        repo = AuthRepository(session)
        deleted = await repo.delete_api_key(key_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="API key not found")


@router.patch(
    "/users/{user_id}/api-keys/{key_id}", response_model=AdminApiKeyResponse
)
async def toggle_api_key(
    user_id: str,
    key_id: str,
    body: ToggleApiKeyRequest,
    db: Database = Depends(require_database),
):
    """Toggle an API key's active state."""
    async with db.session() as session:
        repo = AuthRepository(session)
        api_key = await repo.toggle_api_key(key_id, body.is_active)
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
