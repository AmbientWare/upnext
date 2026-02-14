"""Repository for authentication operations."""

from __future__ import annotations

import hashlib
import logging
import secrets

from sqlalchemy import func, select
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

    # ---- Admin CRUD methods ----

    async def list_users(self) -> list[tuple[User, int]]:
        """Get all users with their API key counts."""
        stmt = (
            select(User, func.count(ApiKey.id).label("key_count"))
            .outerjoin(ApiKey, User.id == ApiKey.user_id)
            .group_by(User.id)
            .order_by(User.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def create_user(self, username: str, is_admin: bool = False) -> User:
        """Create a new user. Raises ValueError if username exists."""
        existing = await self.get_user_by_username(username)
        if existing is not None:
            raise ValueError(f"Username '{username}' already exists")
        user = User(username=username, is_admin=is_admin)
        self._session.add(user)
        await self._session.flush()
        return user

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user by ID. Returns True if deleted."""
        user = await self.get_user_by_id(user_id)
        if user is None:
            return False
        await self._session.delete(user)
        await self._session.flush()
        return True

    async def update_user(
        self, user_id: str, *, is_admin: bool | None = None
    ) -> User | None:
        """Update user fields. Returns updated user or None if not found."""
        user = await self.get_user_by_id(user_id)
        if user is None:
            return None
        if is_admin is not None:
            user.is_admin = is_admin
        await self._session.flush()
        return user

    async def list_api_keys_for_user(self, user_id: str) -> list[ApiKey]:
        """List all API keys for a user."""
        result = await self._session.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_api_key(
        self, user_id: str, name: str = "default"
    ) -> tuple[ApiKey, str]:
        """Create an API key for a user. Returns (ApiKey, raw_key)."""
        raw_key = f"upnxt_{secrets.token_urlsafe(32)}"
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:12]

        api_key = ApiKey(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
        )
        self._session.add(api_key)
        await self._session.flush()
        return api_key, raw_key

    async def delete_api_key(self, key_id: str) -> bool:
        """Delete an API key by ID. Returns True if deleted."""
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.id == key_id)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return False
        await self._session.delete(api_key)
        await self._session.flush()
        return True

    async def rotate_api_key(self, user_id: str) -> tuple[ApiKey, str]:
        """Delete all existing keys for a user and create a fresh one.

        Returns (new_ApiKey, raw_key). Atomic within the current session.
        """
        existing = await self.list_api_keys_for_user(user_id)
        for key in existing:
            await self._session.delete(key)
        await self._session.flush()
        return await self.create_api_key(user_id, "default")

    async def toggle_api_key(self, key_id: str, is_active: bool) -> ApiKey | None:
        """Toggle an API key's active state. Returns updated key or None."""
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.id == key_id)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None
        api_key.is_active = is_active
        await self._session.flush()
        return api_key
