#!/usr/bin/env python3
"""
Load Generator for Conduit testing.

This script generates realistic load against a running Conduit service
to test the system under various conditions.

Usage:
    # Run against local service
    python examples/load_generator.py

    # Run against Docker service
    python examples/load_generator.py --api-url http://localhost:8000

    # Continuous load for 5 minutes
    python examples/load_generator.py --duration 300 --rate 10

    # Burst mode - send many requests quickly
    python examples/load_generator.py --burst 100
"""

import argparse
import asyncio
import random
import time
from dataclasses import dataclass

import aiohttp


@dataclass
class LoadStats:
    """Statistics for load generation."""

    requests_sent: int = 0
    requests_failed: int = 0
    orders_created: int = 0
    tasks_queued: int = 0
    events_emitted: int = 0
    fulfillments_started: int = 0
    start_time: float = 0

    def __str__(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        rate = self.requests_sent / elapsed if elapsed > 0 else 0
        return (
            f"Requests: {self.requests_sent} ({rate:.1f}/s) | "
            f"Failed: {self.requests_failed} | "
            f"Orders: {self.orders_created} | "
            f"Tasks: {self.tasks_queued} | "
            f"Fulfillments: {self.fulfillments_started} | "
            f"Events: {self.events_emitted}"
        )


async def create_order(session: aiohttp.ClientSession, base_url: str, stats: LoadStats):
    """Create a random order."""
    order_data = {
        "id": f"order-{random.randint(10000, 99999)}",
        "items": [
            {
                "product_id": f"prod-{random.randint(1, 100)}",
                "quantity": random.randint(1, 5),
            }
            for _ in range(random.randint(1, 5))
        ],
        "customer_id": f"cust-{random.randint(1, 1000)}",
    }

    try:
        async with session.post(f"{base_url}/orders/", json=order_data) as resp:
            stats.requests_sent += 1
            if resp.status == 200:
                stats.orders_created += 1
            else:
                stats.requests_failed += 1
    except Exception as e:
        stats.requests_failed += 1
        print(f"Error creating order: {e}")


async def generate_test_load(
    session: aiohttp.ClientSession, base_url: str, stats: LoadStats, count: int = 10
):
    """Generate mixed test load."""
    try:
        async with session.post(
            f"{base_url}/test/generate-load", params={"count": count}
        ) as resp:
            stats.requests_sent += 1
            if resp.status == 200:
                stats.tasks_queued += count
            else:
                stats.requests_failed += 1
    except Exception as e:
        stats.requests_failed += 1
        print(f"Error generating load: {e}")


async def emit_test_events(
    session: aiohttp.ClientSession, base_url: str, stats: LoadStats, count: int = 5
):
    """Emit test events."""
    try:
        async with session.post(
            f"{base_url}/test/emit-events", params={"count": count}
        ) as resp:
            stats.requests_sent += 1
            if resp.status == 200:
                stats.events_emitted += count
            else:
                stats.requests_failed += 1
    except Exception as e:
        stats.requests_failed += 1
        print(f"Error emitting events: {e}")


async def fulfill_order(
    session: aiohttp.ClientSession, base_url: str, stats: LoadStats
):
    """Send order fulfillment (includes nested shipping subtask)."""
    try:
        params = {
            "order_id": f"fulfill-order-{random.randint(10000, 99999)}",
            "items_count": random.randint(1, 5),
        }
        async with session.post(
            f"{base_url}/test/fulfill-order", params=params
        ) as resp:
            stats.requests_sent += 1
            if resp.status == 200:
                stats.fulfillments_started += 1
            else:
                stats.requests_failed += 1
    except Exception as e:
        stats.requests_failed += 1
        print(f"Error starting fulfillment: {e}")


async def check_health(
    session: aiohttp.ClientSession, base_url: str, stats: LoadStats
) -> bool:
    """Check service health."""
    try:
        async with session.get(f"{base_url}/health") as resp:
            stats.requests_sent += 1
            return resp.status == 200
    except Exception:
        stats.requests_failed += 1
        return False


async def get_product(session: aiohttp.ClientSession, base_url: str, stats: LoadStats):
    """Get a random product."""
    product_id = f"prod-{random.randint(1, 100)}"
    try:
        async with session.get(f"{base_url}/products/{product_id}") as resp:
            stats.requests_sent += 1
            if resp.status != 200:
                stats.requests_failed += 1
    except Exception:
        stats.requests_failed += 1


async def continuous_load(base_url: str, rate: float, duration: int):
    """Generate continuous load at a specified rate."""
    stats = LoadStats(start_time=time.time())
    interval = 1.0 / rate if rate > 0 else 1.0

    print(f"Starting continuous load: {rate} req/s for {duration}s")
    print(f"Target URL: {base_url}")
    print("-" * 60)

    async with aiohttp.ClientSession() as session:
        # Check health first
        if not await check_health(session, base_url, stats):
            print("Service is not healthy! Aborting.")
            return

        end_time = time.time() + duration
        last_print = time.time()

        while time.time() < end_time:
            # Randomly choose action
            action = random.choices(
                ["order", "load", "events", "product", "health", "fulfillment"],
                weights=[25, 20, 10, 25, 10, 10],
            )[0]

            if action == "order":
                await create_order(session, base_url, stats)
            elif action == "load":
                await generate_test_load(
                    session, base_url, stats, random.randint(5, 20)
                )
            elif action == "events":
                await emit_test_events(session, base_url, stats, random.randint(3, 10))
            elif action == "product":
                await get_product(session, base_url, stats)
            elif action == "fulfillment":
                await fulfill_order(session, base_url, stats)
            else:
                await check_health(session, base_url, stats)

            # Print stats every 5 seconds
            if time.time() - last_print >= 5:
                print(f"[{int(time.time() - stats.start_time):>4}s] {stats}")
                last_print = time.time()

            await asyncio.sleep(interval)

    print("-" * 60)
    print(f"Final: {stats}")


async def burst_load(base_url: str, count: int):
    """Send a burst of requests as fast as possible."""
    stats = LoadStats(start_time=time.time())

    print(f"Starting burst load: {count} requests")
    print(f"Target URL: {base_url}")
    print("-" * 60)

    async with aiohttp.ClientSession() as session:
        # Check health first
        if not await check_health(session, base_url, stats):
            print("Service is not healthy! Aborting.")
            return

        tasks = []
        for i in range(count):
            action = random.choice(
                ["order", "load", "events", "product", "fulfillment"]
            )

            if action == "order":
                tasks.append(create_order(session, base_url, stats))
            elif action == "load":
                tasks.append(
                    generate_test_load(session, base_url, stats, random.randint(5, 15))
                )
            elif action == "events":
                tasks.append(
                    emit_test_events(session, base_url, stats, random.randint(3, 8))
                )
            elif action == "fulfillment":
                tasks.append(fulfill_order(session, base_url, stats))
            else:
                tasks.append(get_product(session, base_url, stats))

            # Batch in groups of 50 to avoid overwhelming
            if len(tasks) >= 50:
                await asyncio.gather(*tasks)
                tasks = []
                print(f"Progress: {stats}")

        if tasks:
            await asyncio.gather(*tasks)

    elapsed = time.time() - stats.start_time
    print("-" * 60)
    print(f"Completed {count} requests in {elapsed:.2f}s ({count / elapsed:.1f} req/s)")
    print(f"Final: {stats}")


async def demo_scenario(base_url: str):
    """Run a demo scenario that exercises all features."""
    stats = LoadStats(start_time=time.time())

    print("Running demo scenario...")
    print(f"Target URL: {base_url}")
    print("-" * 60)

    async with aiohttp.ClientSession() as session:
        # 1. Health check
        print("\n1. Checking service health...")
        if await check_health(session, base_url, stats):
            print("   Service is healthy!")
        else:
            print("   Service is not healthy!")
            return

        # 2. Create some orders
        print("\n2. Creating 10 orders...")
        for i in range(10):
            await create_order(session, base_url, stats)
            await asyncio.sleep(0.1)
        print(f"   Created {stats.orders_created} orders")

        # 3. Generate mixed task load
        print("\n3. Generating mixed task load...")
        await generate_test_load(session, base_url, stats, 50)
        print(f"   Queued {stats.tasks_queued} tasks")

        # 4. Start some order fulfillments
        print("\n4. Starting 5 order fulfillments (with nested shipping subtask)...")
        for _ in range(5):
            await fulfill_order(session, base_url, stats)
            await asyncio.sleep(0.2)
        print(f"   Started {stats.fulfillments_started} fulfillments")

        # 5. Emit events
        print("\n5. Emitting events...")
        await emit_test_events(session, base_url, stats, 20)
        print(f"   Emitted {stats.events_emitted} events")

        # 6. Simulate user browsing
        print("\n6. Simulating user browsing (20 product views)...")
        for _ in range(20):
            await get_product(session, base_url, stats)
            await asyncio.sleep(0.05)

        # 7. Final burst of orders and fulfillments
        print("\n7. Final burst of 20 orders and 5 fulfillments...")
        tasks = [create_order(session, base_url, stats) for _ in range(20)]
        tasks += [fulfill_order(session, base_url, stats) for _ in range(5)]
        await asyncio.gather(*tasks)

    print("-" * 60)
    print(f"Demo completed in {time.time() - stats.start_time:.2f}s")
    print(f"Final: {stats}")


def main():
    parser = argparse.ArgumentParser(description="Load generator for Conduit testing")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080",
        help="Base URL of the Conduit API (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--mode",
        choices=["continuous", "burst", "demo"],
        default="demo",
        help="Load generation mode (default: demo)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Requests per second for continuous mode (default: 5)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds for continuous mode (default: 60)",
    )
    parser.add_argument(
        "--burst",
        type=int,
        default=100,
        help="Number of requests for burst mode (default: 100)",
    )

    args = parser.parse_args()

    if args.mode == "continuous":
        asyncio.run(continuous_load(args.api_url, args.rate, args.duration))
    elif args.mode == "burst":
        asyncio.run(burst_load(args.api_url, args.burst))
    else:
        asyncio.run(demo_scenario(args.api_url))


if __name__ == "__main__":
    main()
