"""Session-scoped repository context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from server.backends.base.repositories import (
    BaseArtifactRepository,
    BaseAuthRepository,
    BaseJobRepository,
    BaseSecretsRepository,
)

RawSessionT = TypeVar("RawSessionT")


@dataclass
class RepositorySession(Generic[RawSessionT]):
    raw_session: RawSessionT
    jobs: BaseJobRepository
    artifacts: BaseArtifactRepository
    auth: BaseAuthRepository
    secrets: BaseSecretsRepository

    async def flush(self) -> None:
        flush = getattr(self.raw_session, "flush", None)
        if flush is not None:
            await flush()

    async def commit(self) -> None:
        commit = getattr(self.raw_session, "commit", None)
        if commit is not None:
            await commit()

    async def rollback(self) -> None:
        rollback = getattr(self.raw_session, "rollback", None)
        if rollback is not None:
            await rollback()

    async def close(self) -> None:
        close = getattr(self.raw_session, "close", None)
        if close is not None:
            await close()

    def __getattr__(self, name: str) -> object:
        return getattr(self.raw_session, name)
