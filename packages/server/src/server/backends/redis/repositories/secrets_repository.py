"""Redis-backed secrets repository."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from pydantic import ValidationError
from redis.asyncio import Redis

from server.backends.base.models import Secret
from server.backends.base.repositories import BaseSecretsRepository
from server.backends.redis.repositories._utils import (
    decode_text,
    dumps,
    loads,
    utcnow,
)
from server.backends.redis.repositories.typing import AsyncRedisClient
from server.crypto import decrypt_data, encrypt_data

_SECRETS_SET = "upnext:persist:secrets:ids"
_SECRETS_BY_NAME = "upnext:persist:secrets:by-name"


def _secret_key(secret_id: str) -> str:
    return f"upnext:persist:secret:{secret_id}"


def _encode_secret(secret: Secret) -> dict[str, str]:
    return {
        "id": secret.id,
        "name": secret.name,
        "encrypted_data": secret.encrypted_data,
        "created_at": secret.created_at.isoformat(),
        "updated_at": secret.updated_at.isoformat(),
    }


def _decode_secret(payload: dict[str, object]) -> Secret | None:
    try:
        return BaseSecretsRepository._to_model(payload)
    except ValidationError:
        return None


class RedisSecretsRepository(BaseSecretsRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis: AsyncRedisClient = cast(AsyncRedisClient, redis)

    async def _read_secret(self, secret_id: str) -> Secret | None:
        payload = loads(await self._redis.get(_secret_key(secret_id)))
        return _decode_secret(payload) if payload else None

    async def _write_secret(self, secret: Secret) -> None:
        await self._redis.set(_secret_key(secret.id), dumps(_encode_secret(secret)))
        await self._redis.sadd(_SECRETS_SET, secret.id)
        await self._redis.hset(_SECRETS_BY_NAME, secret.name, secret.id)

    async def list_secrets(self) -> list[Secret]:
        ids = await self._redis.smembers(_SECRETS_SET)
        out: list[Secret] = []
        for raw_secret_id in ids:
            secret = await self._read_secret(decode_text(raw_secret_id))
            if secret is not None:
                out.append(secret)
        out.sort(key=lambda row: row.created_at, reverse=True)
        return out

    async def get_secret_by_name(self, name: str) -> Secret | None:
        secret_id = await self._redis.hget(_SECRETS_BY_NAME, name)
        if secret_id is None:
            return None
        return await self._read_secret(decode_text(secret_id))

    async def get_secret_by_id(self, secret_id: str) -> Secret | None:
        return await self._read_secret(secret_id)

    async def create_secret(self, name: str, data: dict[str, str]) -> Secret:
        existing = await self.get_secret_by_name(name)
        if existing is not None:
            raise ValueError(f"Secret '{name}' already exists")
        now = utcnow()
        secret = Secret(
            id=str(uuid4()),
            name=name,
            encrypted_data=encrypt_data(data),
            created_at=now,
            updated_at=now,
        )
        await self._write_secret(secret)
        return secret

    async def update_secret(
        self,
        secret_id: str,
        *,
        name: str | None = None,
        data: dict[str, str] | None = None,
    ) -> Secret | None:
        secret = await self.get_secret_by_id(secret_id)
        if secret is None:
            return None
        if name is not None and name != secret.name:
            existing = await self.get_secret_by_name(name)
            if existing is not None and existing.id != secret_id:
                raise ValueError(f"Secret '{name}' already exists")
            await self._redis.hdel(_SECRETS_BY_NAME, secret.name)
            secret.name = name
        if data is not None:
            secret.encrypted_data = encrypt_data(data)
        secret.updated_at = utcnow()
        await self._write_secret(secret)
        return secret

    async def delete_secret(self, secret_id: str) -> bool:
        secret = await self.get_secret_by_id(secret_id)
        if secret is None:
            return False
        await self._redis.delete(_secret_key(secret_id))
        await self._redis.srem(_SECRETS_SET, secret_id)
        await self._redis.hdel(_SECRETS_BY_NAME, secret.name)
        return True

    def decrypt_secret(self, secret: Secret) -> dict[str, str]:
        return decrypt_data(secret.encrypted_data)
