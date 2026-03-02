"""Repository for authentication operations."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.backends.base.models import ApiKey, User
from server.backends.base.repositories import BaseAuthRepository
from server.backends.base.utils import hash_api_key
from server.backends.sql.shared.tables import ApiKeyTable, UserTable

logger = logging.getLogger(__name__)


class PostgresAuthRepository(BaseAuthRepository):
    """Repository for user and API key operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_user_row_by_id(self, user_id: str) -> UserTable | None:
        result = await self._session.execute(
            select(UserTable).where(UserTable.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_api_key_row_by_id(self, key_id: str) -> ApiKeyTable | None:
        result = await self._session.execute(
            select(ApiKeyTable).where(ApiKeyTable.id == key_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(UserTable).where(UserTable.username == username)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        return self._to_model_user(user)

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKeyTable).where(ApiKeyTable.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None
        return self._to_model_api_key(api_key)

    async def get_user_by_id(self, user_id: str) -> User | None:
        user = await self._get_user_row_by_id(user_id)
        if user is None:
            return None
        return self._to_model_user(user)

    async def seed_admin_api_key(self, raw_key: str) -> None:
        """Ensure an admin user exists with the given API key."""
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:8] if len(raw_key) >= 8 else raw_key

        admin = await self.get_user_by_username("admin")
        if admin is None:
            created = UserTable(username="admin", is_admin=True)
            self._session.add(created)
            await self._session.flush()
            admin = self._to_model_user(created)
            logger.info("Created admin user")

        existing = await self.get_api_key_by_hash(key_hash)
        if existing is None:
            api_key = ApiKeyTable(
                user_id=admin.id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                name="seed",
            )
            self._session.add(api_key)
            logger.info("Seed API key created (prefix: %s...)", key_prefix)
        else:
            logger.info("Seed API key already exists (prefix: %s...)", key_prefix)

    async def list_users(self) -> list[tuple[User, int]]:
        stmt = (
            select(UserTable, func.count(ApiKeyTable.id).label("key_count"))
            .outerjoin(ApiKeyTable, UserTable.id == ApiKeyTable.user_id)
            .group_by(UserTable.id)
            .order_by(UserTable.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [(self._to_model_user(row[0]), int(row[1])) for row in result.all()]

    async def create_user(self, username: str, is_admin: bool = False) -> User:
        existing = await self.get_user_by_username(username)
        if existing is not None:
            raise ValueError(f"Username '{username}' already exists")
        user = UserTable(username=username, is_admin=is_admin)
        self._session.add(user)
        await self._session.flush()
        return self._to_model_user(user)

    async def delete_user(self, user_id: str) -> bool:
        user = await self._get_user_row_by_id(user_id)
        if user is None:
            return False
        await self._session.delete(user)
        await self._session.flush()
        return True

    async def update_user(
        self, user_id: str, *, is_admin: bool | None = None
    ) -> User | None:
        user = await self._get_user_row_by_id(user_id)
        if user is None:
            return None
        if is_admin is not None:
            user.is_admin = is_admin
        await self._session.flush()
        return self._to_model_user(user)

    async def list_api_keys_for_user(self, user_id: str) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKeyTable)
            .where(ApiKeyTable.user_id == user_id)
            .order_by(ApiKeyTable.created_at.desc())
        )
        return [self._to_model_api_key(item) for item in result.scalars().all()]

    async def create_api_key(
        self, user_id: str, name: str = "default"
    ) -> tuple[ApiKey, str]:
        raw_key = f"upnxt_{secrets.token_urlsafe(32)}"
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:12]

        api_key = ApiKeyTable(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
        )
        self._session.add(api_key)
        await self._session.flush()
        return self._to_model_api_key(api_key), raw_key

    async def delete_api_key(self, key_id: str) -> bool:
        api_key = await self._get_api_key_row_by_id(key_id)
        if api_key is None:
            return False
        await self._session.delete(api_key)
        await self._session.flush()
        return True

    async def rotate_api_key(self, user_id: str) -> tuple[ApiKey, str]:
        result = await self._session.execute(
            select(ApiKeyTable).where(ApiKeyTable.user_id == user_id)
        )
        for key in result.scalars().all():
            await self._session.delete(key)
        await self._session.flush()
        return await self.create_api_key(user_id, "default")

    async def toggle_api_key(self, key_id: str, is_active: bool) -> ApiKey | None:
        api_key = await self._get_api_key_row_by_id(key_id)
        if api_key is None:
            return None
        api_key.is_active = is_active
        api_key.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_model_api_key(api_key)

    async def save_api_key(self, api_key: ApiKey) -> None:
        existing = await self._get_api_key_row_by_id(api_key.id)
        if existing is None:
            existing = ApiKeyTable(
                id=api_key.id,
                user_id=api_key.user_id,
                key_hash=api_key.key_hash,
                key_prefix=api_key.key_prefix,
                name=api_key.name,
                is_active=api_key.is_active,
                created_at=api_key.created_at,
                updated_at=api_key.updated_at,
                last_used_at=api_key.last_used_at,
            )
            self._session.add(existing)
        else:
            existing.user_id = api_key.user_id
            existing.key_hash = api_key.key_hash
            existing.key_prefix = api_key.key_prefix
            existing.name = api_key.name
            existing.is_active = api_key.is_active
            existing.created_at = api_key.created_at
            existing.updated_at = api_key.updated_at
            existing.last_used_at = api_key.last_used_at
        await self._session.flush()
