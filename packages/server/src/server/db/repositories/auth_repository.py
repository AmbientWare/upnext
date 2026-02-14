"""Repository for authentication operations."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.tables import ApiKey, User

logger = logging.getLogger(__name__)


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class AuthRepository:
    """Repository for user and API key operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def seed_admin_api_key(self, raw_key: str) -> None:
        """Ensure an admin user exists with the given API key."""
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:8] if len(raw_key) >= 8 else raw_key

        # Find or create admin user
        admin = await self.get_user_by_username("admin")
        if admin is None:
            admin = User(username="admin", is_admin=True)
            self._session.add(admin)
            await self._session.flush()
            logger.info("Created admin user")

        # Check if this key already exists
        existing = await self.get_api_key_by_hash(key_hash)
        if existing is None:
            api_key = ApiKey(
                user_id=admin.id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                name="seed",
            )
            self._session.add(api_key)
            logger.info("Seed API key created (prefix: %s...)", key_prefix)
        else:
            logger.info("Seed API key already exists (prefix: %s...)", key_prefix)
