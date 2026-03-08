"""File-based health probe for Docker and Kubernetes liveness checks.

Both Api and Worker heartbeat loops touch a file at HEARTBEAT_INTERVAL_SECONDS.
A container healthcheck can then verify the file is fresh (not older than
HEALTH_STALE_SECONDS) to determine liveness without needing Redis CLI or HTTP.

Usage in Dockerfile / docker-compose:
    healthcheck:
        test: ["CMD", "python", "-m", "upnext.sdk.health"]
        interval: 10s
        timeout: 3s
        retries: 3
"""

import os
import sys
import time

# Single source of truth for heartbeat timing.
HEARTBEAT_INTERVAL_SECONDS = 10

# Consider the process unhealthy if the file hasn't been touched in this many
# seconds (3x the interval allows for transient delays without false alarms).
HEALTH_STALE_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3

HEALTH_FILE = os.environ.get("UPNEXT_HEALTH_FILE", "/tmp/.upnext_alive")


def touch_health_file() -> None:
    """Update the health file modification time (called from heartbeat loops)."""
    try:
        with open(HEALTH_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def check_health() -> bool:
    """Return True if the health file exists and is fresh."""
    try:
        mtime = os.path.getmtime(HEALTH_FILE)
        return (time.time() - mtime) < HEALTH_STALE_SECONDS
    except OSError:
        return False


if __name__ == "__main__":
    # Entry point for Docker healthcheck: python -m upnext.sdk.health
    if check_health():
        sys.exit(0)
    else:
        sys.exit(1)
