# Copyright (c) 2026 Kenneth Stott
# Canary: 38fe1349-4110-4640-95b4-f4da914d989f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Writes the testdata demo's production data, db/*.tsv, which db/init.sql loads (REQ-2053).

A small shop: customers (who sign up and where they live), products, orders and their lines. It
plays the production database; every name, email and order here is generated, from a fixed seed,
so the files are the same on every run. Run it from this directory: python generate.py
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

_DB = Path(__file__).parent / "db"
_FIRST = "Ada Ben Chloe Dev Elena Farah Gus Hana Ivan Jae Kofi Lena Marco Nia Omar Priya Quinn Rosa Sam Tara".split()
_LAST = (
    "Okafor Lindqvist Moreau Tanaka Varga Haddad Ferraro Navarro Shah Amari Brandt Costa".split()
)
_CITIES = {
    "North": ["Leeds", "York", "Durham"],
    "South": ["Brighton", "Exeter", "Bath"],
    "East": ["Norwich", "Ipswich", "Cambridge"],
    "West": ["Bristol", "Cardiff", "Gloucester"],
}
_PRODUCTS = [
    ("Garden hose", "Garden", 24.0),
    ("Trowel", "Garden", 9.5),
    ("Seed tray", "Garden", 6.0),
    ("Chef's knife", "Kitchen", 48.0),
    ("Cast-iron pan", "Kitchen", 39.0),
    ("Tea towel", "Kitchen", 7.5),
    ("Board game", "Games", 32.0),
    ("Jigsaw puzzle", "Games", 18.0),
    ("Card deck", "Games", 5.0),
    ("Cookbook", "Books", 22.0),
    ("Field guide", "Books", 16.5),
    ("Atlas", "Books", 29.0),
]
_STATUS = ["placed", "paid", "shipped", "delivered", "delivered", "delivered", "cancelled"]


def _write(name: str, rows: list[tuple]) -> None:
    lines = ["\t".join("\\N" if v is None else str(v) for v in row) for row in rows]
    (_DB / f"{name}.tsv").write_text("\n".join(lines) + "\n")


def main() -> None:
    rng = random.Random(2053)
    customers = []
    for cid in range(1, 41):
        first, last = rng.choice(_FIRST), rng.choice(_LAST)
        region = rng.choice(sorted(_CITIES))
        customers.append(
            (
                cid,
                f"{first} {last}",
                f"{first.lower()}.{last.lower()}{cid}@example.com",
                rng.choice(_CITIES[region]),
                region,
                date(2024, 1, 1) + timedelta(days=rng.randrange(900)),
            )
        )
    products = [
        (pid, name, category, f"{price:.2f}", rng.randrange(0, 120), f"A {name.lower()}.")
        for pid, (name, category, price) in enumerate(_PRODUCTS, start=1)
    ]
    orders, items = [], []
    for oid in range(1, 121):
        placed = datetime(2026, 1, 1, 8) + timedelta(minutes=rng.randrange(270 * 24 * 60))
        orders.append(
            (oid, rng.randrange(1, 41), placed.strftime("%Y-%m-%d %H:%M:%S"), rng.choice(_STATUS))
        )
        for _ in range(rng.randrange(1, 4)):
            pid, (_n, _c, price) = rng.choice(list(enumerate(_PRODUCTS, start=1)))
            items.append((len(items) + 1, oid, pid, rng.randrange(1, 4), f"{price:.2f}"))
    _write("customers", customers)
    _write("products", products)
    _write("orders", orders)
    _write("order_items", items)


if __name__ == "__main__":
    main()
