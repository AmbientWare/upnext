"""Secrets routes.

- List (names/keys only): any authenticated user
- Get by name (SDK fetch, returns values): any authenticated user by default,
  optionally admin-only via UPNEXT_SECRETS_REQUIRE_ADMIN_READS=true
- Get by ID (returns values, dashboard use): admin only
- Create / Update / Delete: admin only
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from shared.contracts.secrets import (
    CreateSecretRequest,
    SecretDetailResponse,
    SecretResponse,
    SecretsListResponse,
    SecretValuesResponse,
    UpdateSecretRequest,
)

from server.auth import require_admin, require_auth_scope
from server.backends.service import BackendService
from server.config import get_settings
from server.routes.depends import require_backend
from server.runtime_scope import AuthScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", response_model=SecretsListResponse)
async def list_secrets(
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
):
    """List all secrets (key names only, no values)."""
    async with backend.session() as tx:
        secrets = await tx.secrets.list_secrets(deployment_id=scope.deployment_id)

    items = [
        SecretResponse(
            id=s.id,
            name=s.name,
            keys=list(tx.secrets.decrypt_secret(s).keys()),
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in secrets
    ]
    return SecretsListResponse(secrets=items, total=len(items))


@router.get("/by-name/{name}", response_model=SecretValuesResponse)
async def get_secret_by_name(
    name: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
):
    """Fetch a secret's decrypted values by name (for SDK usage)."""
    settings = get_settings()
    if settings.effective_secrets_require_admin_reads:
        if not scope.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

    async with backend.session() as tx:
        secret = await tx.secrets.get_secret_by_name(
            name, deployment_id=scope.deployment_id
        )
        if secret is None:
            raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
        data = tx.secrets.decrypt_secret(secret)

    return SecretValuesResponse(name=secret.name, data=data)


@router.get(
    "/{secret_id}",
    response_model=SecretDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def get_secret(
    secret_id: str,
    scope: AuthScope = Depends(require_admin),
    backend: BackendService = Depends(require_backend),
):
    """Get a secret with decrypted values."""
    async with backend.session() as tx:
        secret = await tx.secrets.get_secret_by_id(
            secret_id, deployment_id=scope.deployment_id
        )
        if secret is None:
            raise HTTPException(status_code=404, detail="Secret not found")
        data = tx.secrets.decrypt_secret(secret)

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
    scope: AuthScope = Depends(require_admin),
    backend: BackendService = Depends(require_backend),
):
    """Create a new named secret."""
    async with backend.session() as tx:
        try:
            secret = await tx.secrets.create_secret(
                body.name,
                body.data,
                deployment_id=scope.deployment_id,
            )
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
    scope: AuthScope = Depends(require_admin),
    backend: BackendService = Depends(require_backend),
):
    """Update a secret's name and/or data."""
    async with backend.session() as tx:
        try:
            secret = await tx.secrets.update_secret(
                secret_id,
                name=body.name,
                data=body.data,
                deployment_id=scope.deployment_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if secret is None:
            raise HTTPException(status_code=404, detail="Secret not found")
        data = tx.secrets.decrypt_secret(secret)

    return SecretDetailResponse(
        id=secret.id,
        name=secret.name,
        data=data,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


@router.delete("/{secret_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_secret(
    secret_id: str,
    scope: AuthScope = Depends(require_admin),
    backend: BackendService = Depends(require_backend),
):
    """Delete a secret."""
    async with backend.session() as tx:
        deleted = await tx.secrets.delete_secret(
            secret_id, deployment_id=scope.deployment_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Secret not found")
