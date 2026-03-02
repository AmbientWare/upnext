from enum import StrEnum


class PersistenceBackends(StrEnum):
    REDIS = "redis"
    POSTGRES = "postgres"
    SQLITE = "sqlite"
