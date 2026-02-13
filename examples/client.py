"""
Traffic generator for the example UpNext service.

Continuously submits jobs to the example service to generate
realistic dashboard data.

Run with: python examples/client.py
"""

import asyncio
import logging
import os
import random

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8001")
INTERVAL_MIN = float(
    os.environ.get("INTERVAL_MIN", "0.5")
)  # Min seconds between requests
INTERVAL_MAX = float(
    os.environ.get("INTERVAL_MAX", "2.0")
)  # Max seconds between requests

# Sample data
PRODUCT_IDS = [f"prod_{i}" for i in range(1, 20)]
ORDER_ITEMS = [
    "Widget A",
    "Widget B",
    "Gadget X",
    "Gadget Y",
    "Component 1",
    "Component 2",
    "Part Alpha",
    "Part Beta",
    "Module Core",
    "Module Plus",
]
NOTIFICATION_MESSAGES = [
    "Your order has been shipped!",
    "Payment confirmed",
    "New feature available",
    "Reminder: Complete your profile",
    "Weekly digest ready",
    "Your subscription expires soon",
    "New message received",
    "Security alert: New login detected",
]
REPORT_TYPES = ["daily", "weekly", "monthly", "inventory", "sales", "users"]
USER_EMAILS = [
    "alice@example.com",
    "bob@example.com",
    "charlie@example.com",
    "diana@example.com",
    "eve@example.com",
]
REMOTE_IMAGE_URLS = [
    "https://httpbin.org/image/png",
    "https://httpbin.org/image/jpeg",
    "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png",
]
REMOTE_PDF_URLS = [
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
]


async def create_order(session: aiohttp.ClientSession) -> dict | None:
    """Submit a new order."""
    items = random.sample(ORDER_ITEMS, k=random.randint(1, 5))
    payload = {
        "user_id": f"user_{random.randint(1, 100)}",
        "items": items,
    }
    try:
        async with session.post(f"{API_URL}/orders", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(
                    f"Created order: {result['order_id']} with {len(items)} items"
                )
                return result
            else:
                logger.warning(f"Failed to create order: {resp.status}")
    except Exception as e:
        logger.error(f"Error creating order: {e}")
    return None


async def send_notification(session: aiohttp.ClientSession) -> dict | None:
    """Send a notification."""
    payload = {
        "user_id": f"user_{random.randint(1, 100)}",
        "message": random.choice(NOTIFICATION_MESSAGES),
        "channel": random.choice(["email", "sms", "push"]),
    }
    try:
        async with session.post(f"{API_URL}/notifications", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Sent notification: {result['job_id']}")
                return result
            else:
                logger.warning(f"Failed to send notification: {resp.status}")
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
    return None


async def request_report(session: aiohttp.ClientSession) -> dict | None:
    """Request a report."""
    payload = {
        "type": random.choice(REPORT_TYPES),
    }
    try:
        async with session.post(f"{API_URL}/reports", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Requested report: {result['report_type']}")
                return result
            else:
                logger.warning(f"Failed to request report: {resp.status}")
    except Exception as e:
        logger.error(f"Error requesting report: {e}")
    return None


async def register_user(session: aiohttp.ClientSession) -> dict | None:
    """Register a new user."""
    payload = {
        "email": random.choice(USER_EMAILS).replace("@", f"{random.randint(1, 999)}@"),
    }
    try:
        async with session.post(f"{API_URL}/users/register", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Registered user: {result['user_id']}")
                return result
            else:
                logger.warning(f"Failed to register user: {resp.status}")
    except Exception as e:
        logger.error(f"Error registering user: {e}")
    return None


async def sync_inventory(session: aiohttp.ClientSession) -> dict | None:
    """Trigger inventory sync."""
    payload = {
        "product_ids": random.sample(PRODUCT_IDS, k=random.randint(2, 8)),
    }
    try:
        async with session.post(f"{API_URL}/inventory/sync", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Syncing inventory for {result['products']} products")
                return result
            else:
                logger.warning(f"Failed to sync inventory: {resp.status}")
    except Exception as e:
        logger.error(f"Error syncing inventory: {e}")
    return None


async def fetch_image_artifact(session: aiohttp.ClientSession) -> dict | None:
    """Trigger remote image fetch and artifact save."""
    url = random.choice(REMOTE_IMAGE_URLS)
    payload = {"url": url}
    try:
        async with session.post(
            f"{API_URL}/artifacts/fetch-image", json=payload
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(
                    f"Submitted image artifact fetch: {result['job_id']} ({url})"
                )
                return result
            else:
                logger.warning(f"Failed to fetch image artifact: {resp.status}")
    except Exception as e:
        logger.error(f"Error fetching image artifact: {e}")
    return None


async def fetch_pdf_artifact(session: aiohttp.ClientSession) -> dict | None:
    """Trigger remote PDF fetch and artifact save."""
    url = random.choice(REMOTE_PDF_URLS)
    payload = {"url": url}
    try:
        async with session.post(f"{API_URL}/artifacts/fetch-pdf", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Submitted PDF artifact fetch: {result['job_id']} ({url})")
                return result
            else:
                logger.warning(f"Failed to fetch PDF artifact: {resp.status}")
    except Exception as e:
        logger.error(f"Error fetching PDF artifact: {e}")
    return None


async def health_check(session: aiohttp.ClientSession) -> bool:
    """Check if the API is healthy."""
    try:
        async with session.get(f"{API_URL}/health") as resp:
            return resp.status == 200
    except Exception:
        return False


async def run_traffic_generator():
    """Main traffic generation loop."""
    logger.info(f"Starting traffic generator for {API_URL}")
    logger.info(f"Interval: {INTERVAL_MIN}s - {INTERVAL_MAX}s between requests")

    # Action weights (relative frequency)
    actions = [
        (create_order, 30),  # Most common
        (send_notification, 25),
        (sync_inventory, 20),
        (register_user, 15),
        (request_report, 10),
        (fetch_image_artifact, 6),
        (fetch_pdf_artifact, 4),  # Least common
    ]

    # Build weighted list
    weighted_actions = []
    for action, weight in actions:
        weighted_actions.extend([action] * weight)

    async with aiohttp.ClientSession() as session:
        # Wait for API to be ready
        logger.info("Waiting for API to be ready...")
        while True:
            if await health_check(session):
                logger.info("API is ready!")
                break
            await asyncio.sleep(2)

        # Generate traffic
        request_count = 0
        while True:
            try:
                # Pick a random action
                action = random.choice(weighted_actions)
                await action(session)

                request_count += 1
                if request_count % 50 == 0:
                    logger.info(f"Total requests sent: {request_count}")

                # Random delay
                delay = random.uniform(INTERVAL_MIN, INTERVAL_MAX)
                await asyncio.sleep(delay)

            except asyncio.CancelledError:
                logger.info("Traffic generator stopped")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run_traffic_generator())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
