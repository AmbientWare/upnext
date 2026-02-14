"""Repository for secrets operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.crypto import decrypt_data, encrypt_data
from server.db.tables import Secret


class SecretsRepository:
    """Repository for secret CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_secrets(self) -> list[Secret]:
        """List all secrets ordered by creation date."""
        result = await self._session.execute(
            select(Secret).order_by(Secret.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_secret_by_name(self, name: str) -> Secret | None:
        result = await self._session.execute(select(Secret).where(Secret.name == name))
        return result.scalar_one_or_none()

    async def get_secret_by_id(self, secret_id: str) -> Secret | None:
        result = await self._session.execute(
            select(Secret).where(Secret.id == secret_id)
        )
        return result.scalar_one_or_none()

    async def create_secret(self, name: str, data: dict[str, str]) -> Secret:
        """Create a new secret. Raises ValueError if name exists."""
        existing = await self.get_secret_by_name(name)
        if existing is not None:
            raise ValueError(f"Secret '{name}' already exists")
        secret = Secret(
            name=name,
            encrypted_data=encrypt_data(data),
        )
        self._session.add(secret)
        await self._session.flush()
        return secret

    async def update_secret(
        self,
        secret_id: str,
        *,
        name: str | None = None,
        data: dict[str, str] | None = None,
    ) -> Secret | None:
        """Update secret name and/or data. Returns None if not found."""
        secret = await self.get_secret_by_id(secret_id)
        if secret is None:
            return None
        if name is not None:
            existing = await self.get_secret_by_name(name)
            if existing is not None and existing.id != secret_id:
                raise ValueError(f"Secret '{name}' already exists")
            secret.name = name
        if data is not None:
            secret.encrypted_data = encrypt_data(data)
        await self._session.flush()
        return secret

    async def delete_secret(self, secret_id: str) -> bool:
        """Delete a secret by ID. Returns True if deleted."""
        secret = await self.get_secret_by_id(secret_id)
        if secret is None:
            return False
        await self._session.delete(secret)
        await self._session.flush()
        return True

    def decrypt_secret(self, secret: Secret) -> dict[str, str]:
        """Decrypt a secret's data."""
        return decrypt_data(secret.encrypted_data)
