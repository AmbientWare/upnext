"""
Example Conduit service demonstrating all features.

Run with: conduit run examples/service.py

This example simulates an e-commerce order processing system with:
- API endpoints for orders, products, and health checks
- Background tasks for order processing, notifications, and analytics
- Cron jobs for cleanup and reporting
- Events for real-time reactions
"""

import asyncio
import random
from datetime import datetime

import conduit

# === Service Setup ===

api = conduit.Api("ecommerce-api", host="0.0.0.0", port=8080)
worker = conduit.Worker(
    "ecommerce-worker", concurrency=100, redis_url="redis://localhost:6379"
)


# === API Routes ===


@api.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# Orders API
orders = api.group("/orders", tags=["orders"])


@orders.get("/")
async def list_orders(limit: int = 10):
    """List recent orders."""
    return {"orders": [], "limit": limit}


@orders.get("/{order_id}")
async def get_order(order_id: str):
    """Get order by ID."""
    return {
        "id": order_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }


@orders.post("/")
async def create_order(data: dict):
    """Create a new order and queue processing."""
    order_id = data.get("id", f"order-{random.randint(1000, 9999)}")

    # Queue the order processing task
    await process_order.submit(order_id=order_id, items=data.get("items", []))

    return {"order_id": order_id, "status": "queued"}


@orders.post("/{order_id}/cancel")
async def cancel_order(order_id: str):
    """Cancel an order."""
    # Send cancellation event
    await order_cancelled.send(order_id=order_id)
    return {"order_id": order_id, "status": "cancelled"}


# Products API
products = api.group("/products", tags=["products"])


@products.get("/")
async def list_products(category: str | None = None):
    """List products."""
    return {"products": [], "category": category}


@products.get("/{product_id}")
async def get_product(product_id: str):
    """Get product details."""
    return {
        "id": product_id,
        "name": f"Product {product_id}",
        "price": random.uniform(10, 100),
    }


# Test endpoints for load generation
test = api.group("/test", tags=["testing"])


@test.post("/generate-load")
async def generate_load(count: int = 10, delay_ms: int = 100):
    """Generate test load by queueing multiple tasks."""
    task_counts = {"fast": 0, "slow": 0, "flaky": 0, "cpu": 0, "fulfillment": 0}

    for i in range(count):
        task_type = random.choice(
            [
                "fast",
                "slow",
                "flaky",
                "cpu",
                "fast",
                "slow",
                "flaky",
                "cpu",
                "fast",
                "fulfillment",
            ]
        )

        if task_type == "fast":
            await fast_task.submit(task_id=f"fast-{i}")
        elif task_type == "slow":
            await slow_task.submit(task_id=f"slow-{i}", duration=random.uniform(2, 5))
        elif task_type == "flaky":
            await flaky_task.submit(task_id=f"flaky-{i}", fail_rate=0.3)
        elif task_type == "fulfillment":
            order_id = f"load-order-{i}-{random.randint(1000, 9999)}"
            items = [
                {"sku": f"SKU-{j}", "qty": random.randint(1, 3)}
                for j in range(random.randint(1, 5))
            ]
            address = {"city": "Test City", "zip": "12345"}
            await fulfill_order_task.submit(
                order_id=order_id,
                items=items,
                shipping_address=address,
            )
        else:
            await cpu_intensive_task.submit(
                task_id=f"cpu-{i}", iterations=random.randint(1000, 5000)
            )

        task_counts[task_type] += 1

    return {
        "queued": count,
        "breakdown": task_counts,
        "message": f"Queued {count} tasks",
    }


@test.post("/emit-events")
async def emit_events(count: int = 5):
    """Emit test events."""
    events = ["order.completed", "order.shipped", "user.signup", "payment.received"]

    event_handles = {
        "order.completed": order_completed,
        "order.shipped": order_shipped,
        "user.signup": user_signup,
        "payment.received": payment_received,
    }

    for i in range(count):
        event_type = random.choice(events)
        handle = event_handles[event_type]
        await handle.send(test_id=i, timestamp=datetime.now().isoformat())

    return {"emitted": count}


# === Background Tasks ===


@worker.task(retries=3, timeout=60.0)
async def process_order(order_id: str, items: list | None = None):
    """
    Process an order through multiple stages.
    Simulates: validation -> payment -> inventory -> shipping
    """
    ctx = conduit.get_current_context()
    items = items or []

    # Stage 1: Validate order
    ctx.set_progress(10, "Validating order...")
    await asyncio.sleep(0.5)

    # Stage 2: Process payment
    ctx.set_progress(30, "Processing payment...")
    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Simulate occasional payment failures
    if random.random() < 0.1:
        raise Exception(f"Payment failed for order {order_id}")

    # Stage 3: Reserve inventory
    ctx.set_progress(50, "Reserving inventory...")
    await asyncio.sleep(0.3)

    # Stage 4: Create shipping label
    ctx.set_progress(70, "Creating shipping label...")
    await asyncio.sleep(0.5)

    # Stage 5: Complete
    ctx.set_progress(100, "Order completed!")

    # Send completion event
    await order_completed.send(order_id=order_id, items_count=len(items))

    return {
        "order_id": order_id,
        "status": "completed",
        "items_processed": len(items),
        "processed_at": datetime.now().isoformat(),
    }


@worker.task(retries=5, timeout=10.0)
async def send_notification(user_id: str, message: str, channel: str = "email"):
    """Send a notification to a user."""
    ctx = conduit.get_current_context()
    ctx.set_progress(50, f"Sending {channel} notification...")

    # Simulate sending
    await asyncio.sleep(random.uniform(0.2, 0.8))

    # Simulate occasional failures
    if random.random() < 0.15:
        raise Exception(f"Failed to send {channel} notification")

    return {"user_id": user_id, "channel": channel, "sent": True}


@worker.task(retries=2, timeout=30.0)
async def generate_report(report_type: str, date_range: dict | None = None):
    """Generate an analytics report."""
    ctx = conduit.get_current_context()

    ctx.set_progress(20, "Gathering data...")
    await asyncio.sleep(1)

    ctx.set_progress(60, "Processing data...")
    await asyncio.sleep(random.uniform(1, 3))

    ctx.set_progress(90, "Formatting report...")
    await asyncio.sleep(0.5)

    return {
        "report_type": report_type,
        "rows": random.randint(100, 10000),
        "generated_at": datetime.now().isoformat(),
    }


# Test tasks with different characteristics


@worker.task(timeout=5.0)
async def fast_task(task_id: str):
    """A fast task that completes quickly."""
    await asyncio.sleep(random.uniform(0.1, 0.3))
    return {"task_id": task_id, "type": "fast", "duration_ms": random.randint(100, 300)}


@worker.task(timeout=30.0)
async def slow_task(task_id: str, duration: float = 3.0):
    """A slow task that takes longer to complete."""
    ctx = conduit.get_current_context()

    steps = 10
    for i in range(steps):
        ctx.set_progress(int((i + 1) / steps * 100), f"Step {i + 1}/{steps}")
        await asyncio.sleep(duration / steps)

    return {"task_id": task_id, "type": "slow", "duration": duration}


@worker.task(retries=3, timeout=10.0)
async def flaky_task(task_id: str, fail_rate: float = 0.3):
    """A task that randomly fails to test retry logic."""
    await asyncio.sleep(random.uniform(0.2, 0.5))

    if random.random() < fail_rate:
        raise Exception(f"Flaky task {task_id} failed (rate: {fail_rate})")

    return {"task_id": task_id, "type": "flaky", "succeeded": True}


@worker.task(timeout=60.0)
async def cpu_intensive_task(task_id: str, iterations: int = 1000):
    """A CPU-intensive task that does computation."""
    ctx = conduit.get_current_context()

    result = 0
    for i in range(iterations):
        result += sum(j * j for j in range(100))
        if i % (iterations // 10) == 0:
            ctx.set_progress(
                int(i / iterations * 100), f"Computing... {i}/{iterations}"
            )
            await asyncio.sleep(0)  # Yield to event loop

    return {
        "task_id": task_id,
        "type": "cpu",
        "iterations": iterations,
        "result": result,
    }


# === Cron Jobs ===


@worker.cron("*/30 * * * * *")  # Every 30 seconds
async def cleanup_expired_carts():
    """Clean up expired shopping carts."""
    cleaned = random.randint(0, 10)
    print(f"[Cron] Cleaned up {cleaned} expired carts")
    return {"cleaned": cleaned, "timestamp": datetime.now().isoformat()}


@worker.cron("0 * * * * *")  # Every minute
async def aggregate_metrics():
    """Aggregate metrics every minute."""
    metrics = {
        "orders_processed": random.randint(10, 100),
        "revenue": random.uniform(1000, 5000),
        "avg_processing_time_ms": random.randint(500, 2000),
    }
    print(f"[Cron] Metrics: {metrics}")
    return metrics


@worker.cron("*/15 * * * * *")  # Every 15 seconds
async def health_ping():
    """Periodic health ping."""
    print("[Cron] Health ping")
    return {"healthy": True, "timestamp": datetime.now().isoformat()}


# === Events ===

order_completed = worker.event("order.completed")
order_shipped = worker.event("order.shipped")
order_cancelled = worker.event("order.cancelled")
user_signup = worker.event("user.signup")
payment_received = worker.event("payment.received")
order_fulfilled = worker.event("order.fulfilled")


@order_completed.on
async def on_order_completed(order_id: str | None = None, items_count: int = 0):
    """React to order completion - send notifications."""
    print(f"[Event] Order completed: {order_id} ({items_count} items)")

    # Queue follow-up tasks
    await send_notification.submit(
        user_id="user-123",
        message=f"Your order {order_id} has been processed!",
        channel="email",
    )

    return {"handled": True, "order_id": order_id}


@order_shipped.on
async def on_order_shipped(order_id: str | None = None, tracking_number: str = "N/A"):
    """React to order shipped event."""
    print(f"[Event] Order shipped: {order_id}, tracking: {tracking_number}")

    await send_notification.submit(
        user_id="user-123",
        message=f"Your order {order_id} has shipped! Tracking: {tracking_number}",
        channel="sms",
    )

    return {"handled": True}


@order_cancelled.on
async def on_order_cancelled(order_id: str | None = None):
    """React to order cancellation."""
    print(f"[Event] Order cancelled: {order_id}")

    # Could send refund process, inventory release, etc.
    return {"handled": True, "order_id": order_id}


@user_signup.on
async def on_user_signup(user_id: str = "unknown"):
    """Welcome new users."""
    print(f"[Event] New user signup: {user_id}")

    await send_notification.submit(
        user_id=user_id, message="Welcome to our platform!", channel="email"
    )

    return {"welcomed": True}


@payment_received.on
async def on_payment_received(amount: float = 0):
    """Process received payments."""
    print(f"[Event] Payment received: ${amount}")
    return {"processed": True, "amount": amount}


# === Fulfillment Tasks ===


@worker.task(timeout=30.0)
async def validate_inventory(order_id: str, items: list[dict]) -> dict:
    """Validate that all items are in stock."""
    ctx = conduit.get_current_context()
    ctx.set_progress(50, "Checking inventory levels...")
    await asyncio.sleep(random.uniform(0.3, 0.8))

    # Simulate occasional out-of-stock
    if random.random() < 0.05:
        raise Exception(f"Item out of stock for order {order_id}")

    return {"order_id": order_id, "items_validated": len(items), "all_in_stock": True}


@worker.task(timeout=30.0)
async def reserve_inventory(order_id: str, items: list[dict]) -> dict:
    """Reserve inventory for the order."""
    ctx = conduit.get_current_context()
    ctx.set_progress(50, "Reserving inventory...")
    await asyncio.sleep(random.uniform(0.2, 0.5))
    return {"order_id": order_id, "items_reserved": len(items)}


@worker.task(timeout=60.0)
async def create_shipping_label(order_id: str, address: dict) -> dict:
    """Create a shipping label with carrier."""
    ctx = conduit.get_current_context()
    ctx.set_progress(30, "Connecting to carrier API...")
    await asyncio.sleep(random.uniform(0.5, 1.0))

    ctx.set_progress(70, "Generating label...")
    await asyncio.sleep(random.uniform(0.3, 0.6))

    tracking_number = f"TRK{random.randint(100000, 999999)}"
    return {
        "order_id": order_id,
        "tracking_number": tracking_number,
        "carrier": "FastShip",
        "label_url": f"https://labels.example.com/{tracking_number}.pdf",
    }


@worker.task(timeout=30.0)
async def schedule_pickup(order_id: str, tracking_number: str) -> dict:
    """Schedule carrier pickup."""
    ctx = conduit.get_current_context()
    ctx.set_progress(50, "Scheduling pickup window...")
    await asyncio.sleep(random.uniform(0.2, 0.4))

    pickup_date = datetime.now().isoformat()
    return {
        "order_id": order_id,
        "tracking_number": tracking_number,
        "pickup_scheduled": pickup_date,
    }


@worker.task(timeout=30.0)
async def notify_warehouse(order_id: str, tracking_number: str) -> dict:
    """Notify warehouse to prepare package."""
    await asyncio.sleep(random.uniform(0.1, 0.3))
    return {"order_id": order_id, "warehouse_notified": True}


@worker.task(timeout=180.0)
async def arrange_shipping(order_id: str, address: dict) -> dict:
    """
    Shipping logistics task with subtasks.

    Handles:
    1. Creating shipping label
    2. Scheduling pickup
    3. Notifying warehouse

    Can be called standalone or as a subtask of another task.
    """
    ctx = conduit.get_current_context()

    # Step 1: Create shipping label
    ctx.set_progress(20, "Creating shipping label...")
    # In a real implementation, we'd wait for the job result
    # For now, simulate the result
    await asyncio.sleep(0.5)
    tracking_number = f"TRK{random.randint(100000, 999999)}"

    # Step 2: Schedule pickup and notify warehouse in parallel
    ctx.set_progress(60, "Scheduling pickup and notifying warehouse...")
    await schedule_pickup.submit(order_id=order_id, tracking_number=tracking_number)
    await notify_warehouse.submit(order_id=order_id, tracking_number=tracking_number)
    await asyncio.sleep(0.3)

    ctx.set_progress(100, "Shipping arranged!")

    return {
        "order_id": order_id,
        "tracking_number": tracking_number,
        "status": "ready_for_pickup",
    }


@worker.task(timeout=300.0)
async def fulfill_order_task(
    order_id: str,
    items: list[dict],
    shipping_address: dict,
) -> dict:
    """
    Order fulfillment task with subtasks.

    Demonstrates tasks calling other tasks — the DAG is implicit
    in the control flow. parent_id is set automatically.

    Stages:
    - Validate inventory
    - Reserve inventory
    - Process payment
    - Arrange shipping (subtask)
    - Send confirmation
    """
    ctx = conduit.get_current_context()
    items = items or []
    shipping_address = shipping_address or {"city": "New York", "zip": "10001"}

    # Stage 1: Validate inventory
    ctx.set_progress(10, "Validating inventory...")
    validate_job_id = await validate_inventory.submit(order_id=order_id, items=items)
    await asyncio.sleep(0.5)  # Simulating wait for task completion

    # Stage 2: Reserve inventory
    ctx.set_progress(25, "Reserving inventory...")
    reserve_job_id = await reserve_inventory.submit(order_id=order_id, items=items)
    await asyncio.sleep(0.3)

    # Stage 3: Process payment
    ctx.set_progress(40, "Processing payment...")
    await asyncio.sleep(random.uniform(0.5, 1.0))

    if random.random() < 0.05:
        raise Exception(f"Payment failed for order {order_id}")

    # Stage 4: Execute shipping subtask
    ctx.set_progress(55, "Arranging shipping...")
    shipping_job_id = await arrange_shipping.submit(
        order_id=order_id,
        address=shipping_address,
    )
    await asyncio.sleep(1.0)

    # Stage 5: Send confirmation
    ctx.set_progress(90, "Sending confirmation...")
    await send_notification.submit(
        user_id="user-123",
        message=f"Order {order_id} confirmed and shipping arranged!",
        channel="email",
    )

    ctx.set_progress(100, "Order fulfilled!")

    # Send fulfillment event
    await order_fulfilled.send(
        order_id=order_id,
        items_count=len(items),
        tracking_number=f"TRK{random.randint(100000, 999999)}",
    )

    return {
        "order_id": order_id,
        "status": "fulfilled",
        "items_processed": len(items),
        "jobs_spawned": {
            "validate_inventory": validate_job_id,
            "reserve_inventory": reserve_job_id,
            "arrange_shipping": shipping_job_id,
        },
        "fulfilled_at": datetime.now().isoformat(),
    }


@test.post("/fulfill-order")
async def fulfill_order(order_id: str | None = None, items_count: int = 3):
    """Send order fulfillment."""
    order_id = order_id or f"order-{random.randint(10000, 99999)}"
    items = [
        {"sku": f"SKU-{i}", "qty": random.randint(1, 5)} for i in range(items_count)
    ]
    address = {
        "street": "123 Main St",
        "city": "New York",
        "state": "NY",
        "zip": "10001",
    }

    job_id = await fulfill_order_task.submit(
        order_id=order_id,
        items=items,
        shipping_address=address,
    )

    return {
        "order_id": order_id,
        "job_id": job_id,
        "status": "started",
    }
