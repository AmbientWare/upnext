"""PostgreSQL SQL backend."""

from server.backends.sql.base import BaseSqlBackend


class PostgresSqlBackend(BaseSqlBackend):
    backend_name = "postgres"
