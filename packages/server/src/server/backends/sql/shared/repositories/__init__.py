from server.backends.base.repository_models import (
    ArtifactRecord,
    FunctionJobStats,
    FunctionWaitStats,
    JobHourlyTrendRow,
    JobRecordCreate,
    PendingArtifactRecord,
)
from server.backends.sql.shared.repositories.artifacts_repository import (
    PostgresArtifactRepository,
)
from server.backends.sql.shared.repositories.jobs_repository import (
    InvalidCursorError,
    PostgresJobRepository,
)
from server.backends.sql.shared.repositories.secrets_repository import (
    PostgresSecretsRepository,
)

# Backward-compatible aliases for callers that used generic names.
JobRepository = PostgresJobRepository
ArtifactRepository = PostgresArtifactRepository
SecretsRepository = PostgresSecretsRepository

__all__ = [
    "PostgresArtifactRepository",
    "ArtifactRepository",
    "ArtifactRecord",
    "FunctionJobStats",
    "FunctionWaitStats",
    "JobHourlyTrendRow",
    "PostgresJobRepository",
    "JobRepository",
    "JobRecordCreate",
    "PendingArtifactRecord",
    "PostgresSecretsRepository",
    "SecretsRepository",
    "InvalidCursorError",
]
