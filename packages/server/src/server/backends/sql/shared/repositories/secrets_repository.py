"""Repository for secrets operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.backends.base.models import Secret
from server.backends.base.repositories import BaseSecretsRepository
from server.backends.sql.shared.tables import SecretTable
from server.crypto import decrypt_data, encrypt_data


class PostgresSecretsRepository(BaseSecretsRepository):
    """Repository for secret CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_secret_row_by_id(self, secret_id: str) -> SecretTable | None:
        result = await self._session.execute(
            select(SecretTable).where(SecretTable.id == secret_id)
        )
        return result.scalar_one_or_none()

    async def _get_secret_row_by_name(self, name: str) -> SecretTable | None:
        result = await self._session.execute(
            select(SecretTable).where(SecretTable.name == name)
        )
        return result.scalar_one_or_none()

    async def list_secrets(self) -> list[Secret]:
        result = await self._session.execute(
            select(SecretTable).order_by(SecretTable.created_at.desc())
        )
        return [self._to_model(row) for row in result.scalars().all()]

    async def get_secret_by_name(self, name: str) -> Secret | None:
        row = await self._get_secret_row_by_name(name)
        if row is None:
            return None
        return self._to_model(row)

    async def get_secret_by_id(self, secret_id: str) -> Secret | None:
        row = await self._get_secret_row_by_id(secret_id)
        if row is None:
            return None
        return self._to_model(row)

    async def create_secret(self, name: str, data: dict[str, str]) -> Secret:
        existing = await self._get_secret_row_by_name(name)
        if existing is not None:
            raise ValueError(f"Secret '{name}' already exists")
        secret = SecretTable(name=name, encrypted_data=encrypt_data(data))
        self._session.add(secret)
        await self._session.flush()
        return self._to_model(secret)

    async def update_secret(
        self,
        secret_id: str,
        *,
        name: str | None = None,
        data: dict[str, str] | None = None,
    ) -> Secret | None:
        secret = await self._get_secret_row_by_id(secret_id)
        if secret is None:
            return None
        if name is not None and name != secret.name:
            existing = await self._get_secret_row_by_name(name)
            if existing is not None and existing.id != secret_id:
                raise ValueError(f"Secret '{name}' already exists")
            secret.name = name
        if data is not None:
            secret.encrypted_data = encrypt_data(data)
        secret.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_model(secret)

    async def delete_secret(self, secret_id: str) -> bool:
        secret = await self._get_secret_row_by_id(secret_id)
        if secret is None:
            return False
        await self._session.delete(secret)
        await self._session.flush()
        return True

    def decrypt_secret(self, secret: Secret) -> dict[str, str]:
        return decrypt_data(secret.encrypted_data)
