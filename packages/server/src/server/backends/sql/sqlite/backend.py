"""SQLite SQL backend."""

from server.backends.sql.base import BaseSqlBackend


class SqliteSqlBackend(BaseSqlBackend):
    backend_name = "sqlite"

    async def prepare_startup(self, required_tables: set[str]) -> None:
        _ = required_tables
        await self.create_tables()
