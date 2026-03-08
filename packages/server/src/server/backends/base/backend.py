"""Abstract persistence backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager

from server.backends.base.repositories import (
    BaseArtifactRepository,
    BaseJobRepository,
)
from server.backends.session_context import RepositorySession


class BaseBackend(ABC):
    """Common contract for all persistence backend implementations."""

    backend_name: str

    @property
    @abstractmethod
    def is_initialized(self) -> bool: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def create_tables(self) -> None: ...

    @abstractmethod
    async def drop_tables(self) -> None: ...

    @abstractmethod
    async def get_missing_tables(self, required_tables: set[str]) -> list[str]: ...

    @abstractmethod
    async def prepare_startup(self, required_tables: set[str]) -> None: ...

    @abstractmethod
    async def check_readiness(self) -> None: ...

    @abstractmethod
    def session(self) -> AbstractAsyncContextManager[RepositorySession]: ...

    @abstractmethod
    def job_repository(self, session: object) -> BaseJobRepository: ...

    @abstractmethod
    def artifact_repository(self, session: object) -> BaseArtifactRepository: ...
