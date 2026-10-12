"""A Python source's code, as an organisation would write it: no import of Provisa's, tags in
docstrings, types in hints (REQ-1993). The same API as the Node fixture's."""

from __future__ import annotations

import asyncio
import enum
import socket
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

print("importing orders")  # what code prints never reaches the protocol


class Tier(enum.Enum):
    GOLD = "gold"
    SILVER = "silver"


@dataclass
class Line:
    sku: str
    qty: int


@dataclass
class Order:
    id: int
    placed: datetime
    due: date
    total: Decimal
    tier: Tier
    lines: list[Line]
    note: str | None = None


def orders(customer_id: str, since: datetime | None = None) -> list[Order]:
    """Orders of one customer.

    @table
    """
    note = since.isoformat() if since else None
    placed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    return [
        Order(
            2**60,
            placed,
            date(2026, 1, 9),
            Decimal("12.50"),
            Tier.GOLD,
            [Line(customer_id, 2)],
            note,
        )
    ]


def many(count: int) -> list[dict]:
    """Rows of no declared shape: typed by a preview.

    @table
    """
    return [{"i": i} for i in range(count)]


async def placed(region: str) -> AsyncIterator[Order]:
    """Orders as they are placed.

    @stream
    """
    n = 0
    while True:
        yield Order(
            n, datetime.now(timezone.utc), date.today(), Decimal(n), Tier.SILVER, [], region
        )
        n += 1
        await asyncio.sleep(0.01)


def ticks() -> Iterator[dict]:
    """@stream"""
    n = 0
    while True:
        yield {"tick": n}
        n += 1
        time.sleep(0.01)


async def forever() -> AsyncIterator[dict]:
    """@stream"""
    await asyncio.Event().wait()
    yield {}


def cancel_order(order_id: int) -> dict:
    """@command"""
    return {"cancelled": order_id}


def boom() -> list[dict]:
    """@table"""
    raise LookupError("no such customer")


def outside() -> list[dict]:
    """@table"""
    with open("/etc/hosts") as hosts:
        return [{"length": len(hosts.read())}]


def fetched(url: str) -> list[dict]:
    """@table"""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return [{"status": response.status, "body": response.read().decode()}]
    except urllib.error.HTTPError as refused:
        return [{"status": refused.code, "body": refused.read().decode()}]


def direct(host: str, port: int) -> list[dict]:
    """@table"""
    with socket.create_connection((host, port), timeout=5):
        return [{"connected": True}]


def helper() -> int:
    return 1
