"""Fetch and inject secrets as environment variables."""

import logging
import os

from upnext.engine.backend_api import BackendAPI

logger = logging.getLogger(__name__)


async def fetch_and_inject_secrets(
    secret_names: list[str],
    backend: BackendAPI,
) -> None:
    """Fetch secrets from the UpNext server and inject as env vars.

    Existing env vars are NOT overwritten (explicit env takes precedence).
    Raises RuntimeError if any secret is not found.
    """
    for name in secret_names:
        data = await backend.get_secret(name)
        if data is None:
            raise RuntimeError(
                f"Secret '{name}' not found on UpNext server. "
                "Create it in the admin dashboard first."
            )
        injected = 0
        for key, value in data.items():
            if key not in os.environ:
                os.environ[key] = value
                injected += 1
        logger.info(
            "Injected secret '%s' (%d vars, %d skipped existing)",
            name,
            injected,
            len(data) - injected,
        )
