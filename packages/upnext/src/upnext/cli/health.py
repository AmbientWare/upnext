"""Health check CLI command."""

import sys

import typer


def health() -> None:
    """Check if the running service is healthy (for use as a K8s probe)."""
    from upnext.sdk.health import check_health

    if check_health():
        sys.exit(0)
    else:
        typer.echo("unhealthy", err=True)
        sys.exit(1)
