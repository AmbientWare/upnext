"""Secrets routes.

- List (names/keys only): any authenticated user
- Get by name (SDK fetch, returns values): any authenticated user by default,
  optionally admin-only via UPNEXT_SECRETS_REQUIRE_ADMIN_READS=true
- Get by ID (returns values, dashboard use): admin only
- Create / Update / Delete: admin only
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from server.auth import require_admin, require_api_key
from server.config import get_settings
from server.db.repositories import SecretsRepository
from server.db.session import Database
from server.db.tables import User
from server.routes.depends import require_database
from shared.contracts.secrets import (
    CreateSecretRequest,
    SecretDetailResponse,
    SecretResponse,
    SecretValuesResponse,
    SecretsListResponse,
    UpdateSecretRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", response_model=SecretsListResponse)
async def list_secrets(db: Database = Depends(require_database)):
    """List all secrets (key names only, no values)."""
    async with db.session() as session:
        repo = SecretsRepository(session)
        secrets = await repo.list_secrets()

    items = [
        SecretResponse(
            id=s.id,
            name=s.name,
            keys=list(repo.decrypt_secret(s).keys()),
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in secrets
    ]
    return SecretsListResponse(secrets=items, total=len(items))


@router.get("/by-name/{name}", response_model=SecretValuesResponse)
async def get_secret_by_name(
    name: str,
    user: User | None = Depends(require_api_key),
    db: Database = Depends(require_database),
):
    """Fetch a secret's decrypted values by name (for SDK usage)."""
    settings = get_settings()
    if settings.effective_secrets_require_admin_reads:
        if user is None or not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

    async with db.session() as session:
        repo = SecretsRepository(session)
        secret = await repo.get_secret_by_name(name)
        if secret is None:
            raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
        data = repo.decrypt_secret(secret)

    return SecretValuesResponse(name=secret.name, data=data)


@router.get(
    "/{secret_id}",
    response_model=SecretDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def get_secret(secret_id: str, db: Database = Depends(require_database)):
    """Get a secret with decrypted values."""
    async with db.session() as session:
        repo = SecretsRepository(session)
        secret = await repo.get_secret_by_id(secret_id)
        if secret is None:
            raise HTTPException(status_code=404, detail="Secret not found")
        data = repo.decrypt_secret(secret)

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        data=data,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


# ---- Admin-only write operations ----


@router.post(
    "",
    response_model=SecretDetailResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_secret(
    body: CreateSecretRequest,
    db: Database = Depends(require_database),
):
    """Create a new named secret."""
    async with db.session() as session:
        repo = SecretsRepository(session)
        try:
            secret = await repo.create_secret(body.name, body.data)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        data=body.data,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


@router.put(
    "/{secret_id}",
    response_model=SecretDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def update_secret(
    secret_id: str,
    body: UpdateSecretRequest,
    db: Database = Depends(require_database),
):
    """Update a secret's name and/or data."""
    async with db.session() as session:
        repo = SecretsRepository(session)
        try:
            secret = await repo.update_secret(
                secret_id, name=body.name, data=body.data
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if secret is None:
            raise HTTPException(status_code=404, detail="Secret not found")
        data = repo.decrypt_secret(secret)

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        data=data,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


@router.delete(
    "/{secret_id}", status_code=204, dependencies=[Depends(require_admin)]
)
async def delete_secret(secret_id: str, db: Database = Depends(require_database)):
    """Delete a secret."""
    async with db.session() as session:
        repo = SecretsRepository(session)
        deleted = await repo.delete_secret(secret_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Secret not found")
