"""
Example UpNext service with worker and API.

Demonstrates:
- Tasks with retries and timeouts
- Cron jobs running every few seconds
- Event handlers
- API endpoints

Run with: upnext run examples/service.py
"""

import asyncio
import base64
import logging
import random
from datetime import datetime
from urllib.parse import urlsplit

import aiohttp
import upnext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create worker and API
worker = upnext.Worker("example-worker", concurrency=100)
api = upnext.Api("example-api", port=8001)

DEFAULT_IMAGE_URL = "https://httpbin.org/image/png"
DEFAULT_PDF_URL = (
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
)
MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10 MB safety cap for demo fetch tasks.


def _guess_name_from_url(url: str, fallback: str) -> str:
    path = urlsplit(url).path.strip()
    if not path:
        return fallback
    candidate = path.rsplit("/", 1)[-1]
    return candidate or fallback


async def _fetch_url_bytes(
    url: str, timeout_s: float = 30.0
) -> tuple[bytes, str | None]:
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            body = await response.read()
            if len(body) > MAX_FETCH_BYTES:
                raise ValueError(
                    f"Fetched payload too large ({len(body)} bytes, max {MAX_FETCH_BYTES})"
                )
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            return body, (content_type or None)


def _image_type_from_content_type(content_type: str | None) -> upnext.ArtifactType:
    if content_type == "image/jpeg":
        return upnext.ArtifactType.JPEG
    if content_type == "image/webp":
        return upnext.ArtifactType.WEBP
    if content_type == "image/gif":
        return upnext.ArtifactType.GIF
    if content_type in {"image/svg", "image/svg+xml"}:
        return upnext.ArtifactType.SVG
    return upnext.ArtifactType.PNG


def _extension_for_image_type(artifact_type: upnext.ArtifactType) -> str:
    if artifact_type == upnext.ArtifactType.JPEG:
        return ".jpg"
    if artifact_type == upnext.ArtifactType.WEBP:
        return ".webp"
    if artifact_type == upnext.ArtifactType.GIF:
        return ".gif"
    if artifact_type == upnext.ArtifactType.SVG:
        return ".svg"
    return ".png"


# =============================================================================
# Tasks
# =============================================================================


@worker.task(retries=3, timeout=30.0)
async def process_order(order_id: str, items: list[str]) -> dict:
    """Process an order - simulates work with progress updates."""
    ctx = upnext.get_current_context()

    logger.info(f"Processing order {order_id} with {len(items)} items")

    for i, item in enumerate(items):
        # Simulate processing each item
        await asyncio.sleep(random.uniform(0.1, 0.5))
        progress = int((i + 1) / len(items) * 100)
        ctx.set_progress(progress, f"Processing {item}")

    # Randomly fail 10% of orders to test retries
    if random.random() < 0.1:
        raise ValueError(f"Failed to process order {order_id}")

    return {"order_id": order_id, "status": "completed", "items_count": len(items)}


@worker.task(retries=2, timeout=10.0)
async def send_notification(user_id: str, message: str, channel: str = "email") -> dict:
    """Send a notification to a user."""

    logger.info(f"Sending {channel} notification to {user_id}: {message[:50]}...")

    # Simulate network latency
    await asyncio.sleep(random.uniform(0.1, 0.3))

    # Create an artifact with the notification details
    await upnext.create_artifact(
        name="notification_sent",
        data={
            "user_id": user_id,
            "channel": channel,
            "sent_at": datetime.now().isoformat(),
        },
    )

    return {"user_id": user_id, "channel": channel, "status": "sent"}


@worker.task
async def generate_report(report_type: str, date_range: dict | None = None) -> dict:
    """Generate a report - a longer running task."""
    ctx = upnext.get_current_context()

    logger.info(f"Generating {report_type} report")

    # Simulate report generation in stages
    stages = ["Collecting data", "Processing", "Formatting", "Saving"]
    for i, stage in enumerate(stages):
        await asyncio.sleep(random.uniform(0.2, 0.5))
        ctx.set_progress(int((i + 1) / len(stages) * 100), stage)

    # Create report artifact
    report_data = {
        "type": report_type,
        "generated_at": datetime.now().isoformat(),
        "rows": random.randint(100, 1000),
    }

    await upnext.create_artifact(
        name=f"report_{report_type}",
        data=report_data,
    )

    return report_data


@worker.task
def sync_inventory(product_ids: list[str]) -> dict:
    """Sync inventory - a synchronous task (runs in thread pool)."""
    import time

    logger.info(f"Syncing inventory for {len(product_ids)} products")

    # Simulate sync work
    time.sleep(random.uniform(0.1, 0.3))

    return {"synced": len(product_ids), "status": "complete"}


@worker.task(retries=1, timeout=45.0)
async def fetch_image_as_artifact(
    url: str = DEFAULT_IMAGE_URL, name: str | None = None
) -> dict:
    """Fetch a remote image and store it as an artifact."""
    ctx = upnext.get_current_context()
    ctx.set_progress(10, "Fetching image")

    payload, content_type = await _fetch_url_bytes(url)
    artifact_type = _image_type_from_content_type(content_type)
    artifact_name = name or _guess_name_from_url(url, "fetched-image")
    if "." not in artifact_name:
        artifact_name = f"{artifact_name}{_extension_for_image_type(artifact_type)}"

    encoded = base64.b64encode(payload).decode("ascii")
    await upnext.create_artifact(
        name=artifact_name,
        data=encoded,
        artifact_type=artifact_type,
    )
    ctx.set_progress(100, "Image artifact saved")

    return {
        "url": url,
        "artifact_name": artifact_name,
        "artifact_type": artifact_type.value,
        "content_type": content_type,
        "size_bytes": len(payload),
    }


@worker.task(retries=1, timeout=45.0)
async def fetch_pdf_as_artifact(
    url: str = DEFAULT_PDF_URL, name: str | None = None
) -> dict:
    """Fetch a remote PDF and store it as an artifact."""
    ctx = upnext.get_current_context()
    ctx.set_progress(10, "Fetching PDF")

    payload, content_type = await _fetch_url_bytes(url)
    artifact_name = name or _guess_name_from_url(url, "fetched-document.pdf")
    if not artifact_name.lower().endswith(".pdf"):
        artifact_name = f"{artifact_name}.pdf"

    encoded = base64.b64encode(payload).decode("ascii")
    await upnext.create_artifact(
        name=artifact_name,
        data=encoded,
        artifact_type=upnext.ArtifactType.PDF,
    )
    ctx.set_progress(100, "PDF artifact saved")

    return {
        "url": url,
        "artifact_name": artifact_name,
        "artifact_type": upnext.ArtifactType.PDF.value,
        "content_type": content_type,
        "size_bytes": len(payload),
    }


@worker.task(timeout=30.0)
async def timeline_demo_step(segment: int, step: int, delay_s: float) -> dict:
    """Leaf task for timeline demo (visible bar growth)."""
    ctx = upnext.get_current_context()
    ctx.set_progress(5, f"Segment {segment} step {step} queued")

    await asyncio.sleep(delay_s * 0.5)
    ctx.set_progress(60, f"Segment {segment} step {step} halfway")

    await asyncio.sleep(delay_s * 0.5)
    ctx.set_progress(100, f"Segment {segment} step {step} complete")

    return {
        "segment": segment,
        "step": step,
        "delay_s": round(delay_s, 2),
    }


@worker.task(timeout=90.0)
async def timeline_demo_segment(segment: int, steps: int = 3) -> dict:
    """Parent task that spawns nested leaf tasks."""
    ctx = upnext.get_current_context()
    completed_steps: list[dict] = []

    for step in range(1, steps + 1):
        delay_s = 0.6 + (step * 0.3)
        step_job = await timeline_demo_step.submit(
            segment=segment,
            step=step,
            delay_s=delay_s,
        )
        completed_steps.append(await step_job.value())

        ctx.set_progress(
            int(step / steps * 100),
            f"Segment {segment}: finished step {step}/{steps}",
        )
        await asyncio.sleep(0.2)

    return {
        "segment": segment,
        "steps": completed_steps,
    }


@worker.task(timeout=240.0)
async def timeline_demo_flow(segments: int = 3) -> dict:
    """Orchestrator task for a multi-level, watchable timeline."""
    ctx = upnext.get_current_context()
    segment_summaries: list[dict] = []

    for segment in range(1, segments + 1):
        await asyncio.sleep(0.4)
        segment_job = await timeline_demo_segment.submit(segment=segment, steps=3)
        segment_summaries.append(await segment_job.value())

        ctx.set_progress(
            int(segment / segments * 100),
            f"Timeline demo: segment {segment}/{segments} complete",
        )

    summary = {
        "ran_at": datetime.now().isoformat(),
        "segments": segment_summaries,
        "segment_count": segments,
    }
    await upnext.create_artifact(name="timeline_demo_summary", data=summary)
    return summary


# =============================================================================
# Cron Jobs
# =============================================================================


@worker.cron("*/5 * * * * *")  # Every 5 seconds
async def health_check():
    """Periodic health check - runs every 5 seconds."""
    logger.info(f"Health check at {datetime.now().isoformat()}")
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@worker.cron("*/15 * * * * *")  # Every 15 seconds
async def metrics_snapshot():
    """Collect metrics snapshot - runs every 15 seconds."""
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "memory_usage": random.randint(100, 500),
        "cpu_usage": random.uniform(0.1, 0.9),
        "active_connections": random.randint(10, 100),
    }
    logger.info(f"Metrics: {metrics}")
    return metrics


@worker.cron("*/30 * * * * *")  # Every 30 seconds
async def cleanup_sessions():
    """Clean up expired sessions - runs every 30 seconds."""
    cleaned = random.randint(0, 10)
    logger.info(f"Cleaned up {cleaned} expired sessions")
    return {"cleaned": cleaned}


@worker.cron("*/20 * * * * *")  # Every 20 seconds
async def timeline_demo_cron():
    """
    Demo run for /jobs timeline view:
    cron root -> flow -> segment -> step (nested tree with visible delays).
    """
    run_label = datetime.now().strftime("%H:%M:%S")
    logger.info(f"Starting timeline demo cron run at {run_label}")

    result = await timeline_demo_flow.wait(segments=3)
    cron_artifact = {
        "run_label": run_label,
        "status": result.status,
        "job_id": result.job_id,
        "saved_at": datetime.now().isoformat(),
    }
    await upnext.create_artifact(
        name="timeline_demo_cron_result",
        data=cron_artifact,
    )
    logger.info(
        "Timeline demo finished: status=%s job_id=%s",
        result.status,
        result.job_id,
    )
    return cron_artifact


# =============================================================================
# Events
# =============================================================================

order_placed = worker.event("order.placed")
user_registered = worker.event("user.registered")


@order_placed.on
async def on_order_send_confirmation(order_id: str, user_id: str, **kwargs):
    """Send order confirmation when an order is placed."""
    logger.info(f"Sending confirmation for order {order_id} to user {user_id}")
    await asyncio.sleep(0.1)
    return {"confirmation_sent": True}


@order_placed.on(retries=2)
async def on_order_update_inventory(items: list[str] | None = None, **kwargs):
    """Update inventory when an order is placed."""
    items = items or []
    logger.info(f"Updating inventory for {len(items)} items")
    await asyncio.sleep(0.2)
    return {"inventory_updated": True}


@user_registered.on
async def on_user_send_welcome(user_id: str, email: str, **kwargs):
    """Send welcome email when a user registers."""
    logger.info(f"Sending welcome email to {email}")
    await asyncio.sleep(0.1)
    return {"welcome_sent": True}


# =============================================================================
# API Endpoints
# =============================================================================


@api.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "example-api"}


@api.post("/orders")
async def create_order(order: dict):
    """Create a new order - submits to worker."""
    order_id = f"order_{random.randint(1000, 9999)}"
    items = order.get("items", ["item1", "item2"])

    # Submit order processing task
    job = await process_order.submit(order_id=order_id, items=items)

    # Emit order placed event
    await order_placed.send(
        order_id=order_id, user_id=order.get("user_id", "user_1"), items=items
    )

    return {"order_id": order_id, "job_id": job.job_id, "status": "submitted"}


@api.post("/notifications")
async def send_user_notification(notification: dict):
    """Send a notification - submits to worker."""
    user_id = notification.get("user_id", "user_1")
    message = notification.get("message", "Hello!")
    channel = notification.get("channel", "email")

    job = await send_notification.submit(
        user_id=user_id, message=message, channel=channel
    )

    return {"job_id": job.job_id, "status": "submitted"}


@api.post("/reports")
async def request_report(request: dict):
    """Request a report - submits to worker."""
    report_type = request.get("type", "daily")

    job = await generate_report.submit(
        report_type=report_type, date_range=request.get("date_range")
    )

    return {"job_id": job.job_id, "report_type": report_type, "status": "submitted"}


@api.post("/users/register")
async def register_user(user: dict):
    """Register a new user - emits event."""
    user_id = f"user_{random.randint(1000, 9999)}"
    email = user.get("email", f"{user_id}@example.com")

    # Emit user registered event
    await user_registered.send(user_id=user_id, email=email)

    return {"user_id": user_id, "email": email, "status": "registered"}


@api.post("/inventory/sync")
async def trigger_inventory_sync(request: dict):
    """Trigger inventory sync - submits to worker."""
    product_ids = request.get("product_ids", ["prod_1", "prod_2", "prod_3"])

    job = await sync_inventory.submit(product_ids=product_ids)

    return {"job_id": job.job_id, "products": len(product_ids), "status": "submitted"}


@api.post("/artifacts/fetch-image")
async def fetch_remote_image(request: dict):
    """Fetch a remote image URL and save it as an artifact."""
    url = request.get("url", DEFAULT_IMAGE_URL)
    name = request.get("name")
    job = await fetch_image_as_artifact.submit(url=url, name=name)
    return {
        "job_id": job.job_id,
        "status": "submitted",
        "url": url,
    }


@api.post("/artifacts/fetch-pdf")
async def fetch_remote_pdf(request: dict):
    """Fetch a remote PDF URL and save it as an artifact."""
    url = request.get("url", DEFAULT_PDF_URL)
    name = request.get("name")
    job = await fetch_pdf_as_artifact.submit(url=url, name=name)
    return {
        "job_id": job.job_id,
        "status": "submitted",
        "url": url,
    }


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    upnext.run(api, worker)
