"""Redis-backed auth repository."""

from __future__ import annotations

import secrets
from dataclasses import replace
from typing import cast
from uuid import uuid4

from pydantic import ValidationError
from redis.asyncio import Redis

from server.backends.base.models import ApiKey, User
from server.backends.base.repositories import BaseAuthRepository
from server.backends.base.utils import hash_api_key
from server.backends.redis.repositories._utils import (
    decode_text,
    dumps,
    loads,
    utcnow,
)
from server.backends.redis.repositories.typing import AsyncRedisClient

_USERS_SET = "upnext:persist:auth:users"
_USERS_BY_USERNAME = "upnext:persist:auth:users:by-username"
_API_KEYS_SET = "upnext:persist:auth:api-keys"
_API_KEYS_BY_HASH = "upnext:persist:auth:api-keys:by-hash"


def _user_key(user_id: str) -> str:
    return f"upnext:persist:auth:user:{user_id}"


def _api_key_key(key_id: str) -> str:
    return f"upnext:persist:auth:api-key:{key_id}"


def _user_api_keys_key(user_id: str) -> str:
    return f"upnext:persist:auth:user:{user_id}:api-keys"


def _encode_user(user: User) -> dict[str, str]:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": "1" if user.is_admin else "0",
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def _decode_user(payload: dict[str, object]) -> User | None:
    normalized = dict(payload)
    normalized["is_admin"] = decode_text(payload.get("is_admin", "0")) == "1"
    try:
        return BaseAuthRepository._to_model_user(normalized)
    except ValidationError:
        return None


def _encode_api_key(api_key: ApiKey) -> dict[str, str]:
    return {
        "id": api_key.id,
        "user_id": api_key.user_id,
        "key_hash": api_key.key_hash,
        "key_prefix": api_key.key_prefix,
        "name": api_key.name,
        "is_active": "1" if api_key.is_active else "0",
        "created_at": api_key.created_at.isoformat(),
        "updated_at": api_key.updated_at.isoformat(),
        "last_used_at": api_key.last_used_at.isoformat()
        if api_key.last_used_at
        else "",
    }


def _decode_api_key(payload: dict[str, object]) -> ApiKey | None:
    normalized = dict(payload)
    normalized["is_active"] = decode_text(payload.get("is_active", "1")) == "1"
    if payload.get("last_used_at") in ("", None):
        normalized["last_used_at"] = None
    try:
        return BaseAuthRepository._to_model_api_key(normalized)
    except ValidationError:
        return None


class RedisAuthRepository(BaseAuthRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis: AsyncRedisClient = cast(AsyncRedisClient, redis)

    async def _read_user(self, user_id: str) -> User | None:
        payload = loads(await self._redis.get(_user_key(user_id)))
        return _decode_user(payload) if payload else None

    async def _write_user(self, user: User) -> None:
        await self._redis.set(_user_key(user.id), dumps(_encode_user(user)))
        await self._redis.sadd(_USERS_SET, user.id)
        await self._redis.hset(_USERS_BY_USERNAME, user.username, user.id)

    async def _read_api_key(self, key_id: str) -> ApiKey | None:
        payload = loads(await self._redis.get(_api_key_key(key_id)))
        return _decode_api_key(payload) if payload else None

    async def _write_api_key(self, key: ApiKey) -> None:
        await self._redis.set(_api_key_key(key.id), dumps(_encode_api_key(key)))
        await self._redis.sadd(_API_KEYS_SET, key.id)
        await self._redis.hset(_API_KEYS_BY_HASH, key.key_hash, key.id)
        await self._redis.sadd(_user_api_keys_key(key.user_id), key.id)

    async def get_user_by_username(self, username: str) -> User | None:
        user_id = await self._redis.hget(_USERS_BY_USERNAME, username)
        if user_id is None:
            return None
        return await self._read_user(decode_text(user_id))

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        key_id = await self._redis.hget(_API_KEYS_BY_HASH, key_hash)
        if key_id is None:
            return None
        return await self._read_api_key(decode_text(key_id))

    async def get_user_by_id(self, user_id: str) -> User | None:
        return await self._read_user(user_id)

    async def seed_admin_api_key(self, raw_key: str) -> None:
        key_hash_value = hash_api_key(raw_key)
        key_prefix = raw_key[:8] if len(raw_key) >= 8 else raw_key
        admin = await self.get_user_by_username("admin")
        if admin is None:
            admin = await self.create_user("admin", True)
        existing = await self.get_api_key_by_hash(key_hash_value)
        if existing is not None:
            return
        key = ApiKey(
            id=str(uuid4()),
            user_id=admin.id,
            key_hash=key_hash_value,
            key_prefix=key_prefix,
            name="seed",
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
            last_used_at=None,
        )
        await self._write_api_key(key)

    async def list_users(self) -> list[tuple[User, int]]:
        user_ids = await self._redis.smembers(_USERS_SET)
        out: list[tuple[User, int]] = []
        for raw_user_id in user_ids:
            user = await self._read_user(decode_text(raw_user_id))
            if user is None:
                continue
            key_count = await self._redis.scard(_user_api_keys_key(user.id))
            out.append((user, int(key_count)))
        out.sort(key=lambda row: row[0].created_at, reverse=True)
        return out

    async def create_user(self, username: str, is_admin: bool = False) -> User:
        existing = await self.get_user_by_username(username)
        if existing is not None:
            raise ValueError(f"Username '{username}' already exists")
        now = utcnow()
        user = User(
            id=str(uuid4()),
            username=username,
            is_admin=is_admin,
            created_at=now,
            updated_at=now,
        )
        await self._write_user(user)
        return user

    async def delete_user(self, user_id: str) -> bool:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return False
        key_ids = await self._redis.smembers(_user_api_keys_key(user_id))
        for raw_key_id in key_ids:
            key_id = decode_text(raw_key_id)
            api_key = await self._read_api_key(key_id)
            if api_key:
                await self._redis.hdel(_API_KEYS_BY_HASH, api_key.key_hash)
                await self._redis.srem(_API_KEYS_SET, key_id)
                await self._redis.delete(_api_key_key(key_id))
        await self._redis.delete(_user_api_keys_key(user_id))
        await self._redis.hdel(_USERS_BY_USERNAME, user.username)
        await self._redis.srem(_USERS_SET, user_id)
        await self._redis.delete(_user_key(user_id))
        return True

    async def update_user(
        self, user_id: str, *, is_admin: bool | None = None
    ) -> User | None:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return None
        if is_admin is not None:
            user = replace(user, is_admin=is_admin, updated_at=utcnow())
        await self._write_user(user)
        return user

    async def list_api_keys_for_user(self, user_id: str) -> list[ApiKey]:
        key_ids = await self._redis.smembers(_user_api_keys_key(user_id))
        out: list[ApiKey] = []
        for raw_key_id in key_ids:
            key = await self._read_api_key(decode_text(raw_key_id))
            if key is not None:
                out.append(key)
        out.sort(key=lambda row: row.created_at, reverse=True)
        return out

    async def create_api_key(
        self, user_id: str, name: str = "default"
    ) -> tuple[ApiKey, str]:
        raw_key = f"upnxt_{secrets.token_urlsafe(32)}"
        key_hash_value = hash_api_key(raw_key)
        key_prefix = raw_key[:12]
        api_key = ApiKey(
            id=str(uuid4()),
            user_id=user_id,
            key_hash=key_hash_value,
            key_prefix=key_prefix,
            name=name,
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
            last_used_at=None,
        )
        await self._write_api_key(api_key)
        return api_key, raw_key

    async def delete_api_key(self, key_id: str) -> bool:
        api_key = await self._read_api_key(key_id)
        if api_key is None:
            return False
        await self._redis.hdel(_API_KEYS_BY_HASH, api_key.key_hash)
        await self._redis.srem(_user_api_keys_key(api_key.user_id), key_id)
        await self._redis.srem(_API_KEYS_SET, key_id)
        await self._redis.delete(_api_key_key(key_id))
        return True

    async def rotate_api_key(self, user_id: str) -> tuple[ApiKey, str]:
        existing = await self.list_api_keys_for_user(user_id)
        for key in existing:
            await self.delete_api_key(key.id)
        return await self.create_api_key(user_id, "default")

    async def toggle_api_key(self, key_id: str, is_active: bool) -> ApiKey | None:
        key = await self._read_api_key(key_id)
        if key is None:
            return None
        key.is_active = is_active
        key.updated_at = utcnow()
        await self._write_api_key(key)
        return key

    async def save_api_key(self, api_key: ApiKey) -> None:
        await self._write_api_key(api_key)
