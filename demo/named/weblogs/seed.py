# Copyright (c) 2026 Kenneth Stott
# Canary: c9060448-f704-4faf-8e22-6342a31aa3fc
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The weblogs demo's traffic (REQ-1858, REQ-1996): the `seeder` service sends the shop a fixed
mix of requests through nginx, so the access log and the database log have something to show.

The mix comes from a fixed seed, so every start sends the same requests: browsing, searches (some
ranked by sales, which is slow), product and order pages, orders placed, the back office's slow
report, and the failures a shop has -- unknown ids (404), bad input (400), an order beyond the
stock or for an unknown customer and a page whose column is gone (database errors, 500). It sends
REQUESTS of them and stops, so the logs hold one bounded run. A marker on the data directory
makes a restart with kept data send nothing."""

from __future__ import annotations

import http.client
import json
import os
import random
import sys
from pathlib import Path

MARKER = Path("/data-marker/.seeded")
HOST = os.environ["SHOP_HOST"]
PORT = int(os.environ["SHOP_PORT"])
REQUESTS = 1500

AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "shop-mobile/4.2 (Android 14)",
]
WORDS = ["trail", "lamp", "kettle", "jacket", "mug", "studio", "harbor", "light", "classic", "zzz"]
CATEGORIES = ["outdoor", "home", "kitchen", "apparel", "office", "audio"]


def _request(rng: random.Random) -> tuple[str, str, dict | None]:
    """One request of the mix: its method, path and JSON body."""
    pick = rng.random()
    if pick < 0.28:
        if rng.random() < 0.4:
            return "GET", f"/products?category={rng.choice(CATEGORIES)}", None
        return "GET", f"/products?page={rng.choice([1, 1, 1, 2, 2, 3, 0])}", None
    if pick < 0.53:
        # Products 81-120 are browsed and never bought; 121-130 do not exist.
        return "GET", f"/products/{rng.randint(1, 130)}", None
    if pick < 0.66:
        q = rng.choice(WORDS) if rng.random() > 0.03 else "%20"
        sort = "popular" if rng.random() < 0.25 else "name"
        return "GET", f"/search?q={q}&sort={sort}", None
    if pick < 0.74:
        return "GET", f"/customers/{rng.randint(1, 210)}/orders", None
    if pick < 0.81:
        return "GET", f"/orders/{rng.randint(1, 1080)}", None
    if pick < 0.96:
        body = {
            # A customer 201-205 does not exist: the order fails in the database.
            "customer_id": rng.randint(1, 205),
            "product_id": rng.randint(1, 82),
            "quantity": rng.choice([1, 1, 1, 2, 2, 3, 4, 6, 0, 12]),
        }
        return "POST", "/orders", body
    if pick < 0.985:
        return "GET", "/reports/top", None
    return "GET", "/wishlist", None


def main() -> None:
    if MARKER.exists():
        print("weblogs: traffic already sent; nothing to do")
        return
    rng = random.Random(1858)
    statuses: dict[int, int] = {}
    conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
    for _ in range(REQUESTS):
        method, path, body = _request(rng)
        customer = rng.randint(1, 200)
        headers = {
            "User-Agent": rng.choice(AGENTS),
            # nginx takes the client from X-Forwarded-For: each customer browses from an address
            # of their own.
            "X-Forwarded-For": f"203.0.113.{customer % 250 + 1}",
        }
        if rng.random() < 0.7:
            headers["Cookie"] = f"customer={customer}"
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        response.read()
        statuses[response.status] = statuses.get(response.status, 0) + 1
    conn.close()
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps(statuses, sort_keys=True))
    print(f"weblogs: sent {REQUESTS} requests: {json.dumps(statuses, sort_keys=True)}")
    if not statuses.keys() & {200, 201}:
        sys.exit("weblogs: the shop answered no request")


if __name__ == "__main__":
    main()
