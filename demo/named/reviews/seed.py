# Copyright (c) 2026 Kenneth Stott
# Canary: 487adeb2-3ef0-4a5b-9af2-24fe7045910f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The reviews demo's data (REQ-2030), written once by the `seeder` service into its three stores.

An electronics shop keeps its catalog in MongoDB, the reviews its customers write in Elasticsearch
and who bought what in Neo4j, all keyed by one product id:

  MongoDB catalog        products (200 documents, specs nested) and ratings (one a star rating)
  Elasticsearch reviews  5,000 reviews: a title, the text, the stars, the product and the customer
  Neo4j                  2,000 (:Customer) nodes, the (:Product) nodes, (:Customer)-[:BOUGHT]->(:Product)

Every value is invented here, from a fixed seed, so every start writes the same data. A few battery
products have a weak battery: their reviews say the battery dies, their ratings are lower, and the
customers who bought them often bought a power bank too -- the story the demo's tour follows. A
marker on the data directory, holding how many of each it wrote, makes a restart with kept data
write nothing."""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from pymongo import MongoClient

MARKER = Path("/data-marker/.seeded")
MONGO_URL = os.environ["MONGO_URL"]
ES_URL = os.environ["ES_URL"]
NEO4J_URL = os.environ["NEO4J_URL"]

PRODUCTS = 200
CUSTOMERS = 2000
REVIEWS = 5000
START = date(2026, 1, 1)
DAYS = 270

BRANDS = ["Voltra", "Lumen", "Kestrel", "Nimbus", "Arden", "Cobalt", "Juniper", "Halcyon"]
# category: (models, price range, battery hours or None)
CATEGORIES = {
    "headphones": (["Air", "Studio", "Pulse", "Drift", "Echo"], (39, 349), (18, 60)),
    "phone": (["One", "Edge", "Lite", "Max", "Mini"], (199, 1199), (20, 40)),
    "laptop": (["Book", "Slate", "Forge", "Aero"], (499, 2499), (8, 22)),
    "smartwatch": (["Fit", "Sport", "Classic", "Trail"], (99, 499), (24, 120)),
    "speaker": (["Boom", "Room", "Go", "Wave"], (29, 399), (8, 30)),
    "camera": (["Shot", "Vista", "Pro", "Snap"], (149, 1899), (3, 8)),
    "power bank": (["Cell", "Reserve", "Tank", "Pocket"], (19, 129), None),
    "charger": (["Dock", "Plug", "Duo", "Wall"], (12, 89), None),
    "case": (["Shell", "Guard", "Folio", "Grip"], (9, 59), None),
    "cable": (["Link", "Braid", "Flex"], (6, 39), None),
}
# What a buyer of a category also picks up, most likely first.
COMPANIONS = {
    "headphones": ["case", "cable", "charger"],
    "phone": ["case", "charger", "power bank", "cable"],
    "laptop": ["charger", "cable", "case"],
    "smartwatch": ["charger", "cable"],
    "speaker": ["cable", "power bank"],
    "camera": ["case", "power bank", "cable"],
}
FIRST = [
    "Ava",
    "Ben",
    "Chloe",
    "Dev",
    "Elena",
    "Femi",
    "Grace",
    "Hugo",
    "Iris",
    "Jonah",
    "Kai",
    "Lena",
    "Mateo",
    "Nora",
    "Omar",
    "Priya",
    "Quinn",
    "Rosa",
    "Sami",
    "Tara",
    "Uma",
    "Viktor",
    "Wren",
    "Yusuf",
    "Zoe",
]
LAST = [
    "Abbott",
    "Banerjee",
    "Castillo",
    "Dimitrov",
    "Eze",
    "Fischer",
    "Gallagher",
    "Haddad",
    "Ito",
    "Jensen",
    "Kowalski",
    "Larsen",
    "Moreau",
    "Nakamura",
    "Okafor",
    "Petrov",
    "Quint",
    "Rossi",
    "Sato",
    "Tanaka",
    "Underwood",
    "Varga",
    "Whitfield",
    "Yilmaz",
    "Zielinski",
]
CITIES = ["Austin", "Boston", "Chicago", "Denver", "Miami", "Portland", "Seattle", "Toronto"]

PRAISE = [
    "Exactly what I wanted.",
    "Sound is clear and the build feels solid.",
    "Setup took a minute.",
    "Great value for the price.",
    "Looks even better in person.",
    "Works perfectly with my laptop.",
    "Fast shipping and well packed.",
    "Would buy again.",
    "Comfortable to use all day.",
]
GRIPES = [
    "The buttons feel cheap.",
    "Instructions were confusing.",
    "A bit heavier than expected.",
    "The app keeps asking me to sign in.",
    "Arrived with a scratch on the side.",
    "Bluetooth drops now and then.",
]
BATTERY_GOOD = [
    "The battery lasts all week.",
    "Battery life is excellent.",
    "Charges quickly and holds it.",
]
BATTERY_DIES = [
    "The battery dies after two hours.",
    "By lunchtime the battery dies.",
    "Battery dies overnight even when it is switched off.",
    "Great until the battery dies, which is constantly.",
    "Returned it because the battery dies so fast.",
]


def _catalog(rng: random.Random) -> list[dict]:
    products = []
    names = set()
    while len(products) < PRODUCTS:
        category = rng.choice(list(CATEGORIES))
        models, (low, high), battery = CATEGORIES[category]
        brand = rng.choice(BRANDS)
        name = f"{brand} {rng.choice(models)} {rng.randint(2, 9)}{rng.choice(['', 'S', 'X'])}"
        if (name, category) in names:
            continue
        names.add((name, category))
        product = {
            "_id": len(products) + 1,
            "product_id": len(products) + 1,
            "name": f"{name} {category}" if category in ("power bank", "case", "cable") else name,
            "category": category,
            "brand": brand,
            "price": round(rng.uniform(low, high), 2),
            "launched": (START - timedelta(days=rng.randint(30, 900))).isoformat(),
            "specs": {"weight_g": rng.randint(20, 2200)},
            "tags": rng.sample(["wireless", "usb-c", "fast-charge", "waterproof", "compact"], 2),
        }
        if battery is not None:
            product["specs"]["battery_hours"] = rng.randint(*battery)
        products.append(product)
    battery_products = [p for p in products if "battery_hours" in p["specs"]]
    for product in rng.sample(battery_products, 12):
        product["weak_battery"] = True
        product["specs"]["battery_hours"] = max(2, product["specs"]["battery_hours"] // 4)
    return products


def _customers(rng: random.Random) -> list[dict]:
    return [
        {
            "customer_id": i,
            "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            "city": rng.choice(CITIES),
            "joined": (START - timedelta(days=rng.randint(0, 1500))).isoformat(),
        }
        for i in range(1, CUSTOMERS + 1)
    ]


def _purchases(rng: random.Random, products: list[dict]) -> list[dict]:
    """Who bought what: a device, then its companions; a weak battery's buyer likely a power bank."""
    by_category: dict[str, list[dict]] = {}
    for p in products:
        by_category.setdefault(p["category"], []).append(p)
    devices = [p for p in products if p["category"] in COMPANIONS]
    weak = [p for p in devices if p.get("weak_battery")]
    bought = []
    for customer in range(1, CUSTOMERS + 1):
        basket = {}
        for _ in range(rng.choice([1, 1, 2, 2, 3])):
            device = rng.choice(weak) if rng.random() < 0.15 else rng.choice(devices)
            basket[device["_id"]] = device
            for i, category in enumerate(COMPANIONS[device["category"]]):
                if rng.random() < 0.45 / (i + 1):
                    extra = rng.choice(by_category[category])
                    basket[extra["_id"]] = extra
            if device.get("weak_battery") and rng.random() < 0.7:
                extra = rng.choice(by_category["power bank"])
                basket[extra["_id"]] = extra
        for product_id in basket:
            day = START + timedelta(days=rng.randrange(DAYS))
            bought.append(
                {"customer_id": customer, "product_id": product_id, "on": day.isoformat()}
            )
    return bought


def _review(rng: random.Random, product: dict, customer_id: int, n: int, on: str) -> dict:
    has_battery = "battery_hours" in product["specs"]
    weak = product.get("weak_battery", False)
    if weak and rng.random() < 0.55:
        stars = rng.choice([1, 1, 2, 2, 3])
        sentences = [rng.choice(BATTERY_DIES), rng.choice(GRIPES + PRAISE)]
        title = rng.choice(["Battery is a letdown", "Dies too fast", "Not for long days"])
    else:
        stars = rng.choices(
            [1, 2, 3, 4, 5], weights=[1, 1, 3, 7, 8] if not weak else [2, 3, 4, 3, 2]
        )[0]
        pool = PRAISE if stars >= 4 else GRIPES
        sentences = rng.sample(pool, 2)
        if has_battery and rng.random() < 0.4:
            sentences.append(rng.choice(BATTERY_GOOD if not weak else BATTERY_GOOD + BATTERY_DIES))
        title = (
            rng.choice(["Love it", "Solid", "Does the job", "Good buy"])
            if stars >= 4
            else (rng.choice(["Mixed feelings", "Could be better", "Disappointed"]))
        )
    return {
        "review_id": f"r{n:05d}",
        "product_id": product["_id"],
        "customer_id": customer_id,
        "rating": stars,
        "title": title,
        "text": " ".join(sentences),
        "created_at": on,
    }


def _http(method: str, url: str, body: bytes | None, content_type: str) -> dict:
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", content_type)
    with urllib.request.urlopen(request, timeout=120) as response:
        text = response.read().decode()
    return json.loads(text) if text else {}


def _seed_mongo(products: list[dict], ratings: list[dict]) -> None:
    db = MongoClient(MONGO_URL)["catalog"]
    db.products.drop()
    db.ratings.drop()
    db.products.insert_many([{k: v for k, v in p.items() if k != "weak_battery"} for p in products])
    db.ratings.insert_many(ratings)
    db.ratings.create_index("product_id")


def _seed_es(reviews: list[dict]) -> None:
    try:
        _http("DELETE", f"{ES_URL}/reviews", None, "application/json")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    mappings = {
        "properties": {
            "review_id": {"type": "keyword"},
            "product_id": {"type": "integer"},
            "customer_id": {"type": "integer"},
            "rating": {"type": "integer"},
            "title": {"type": "text"},
            "text": {"type": "text"},
            "created_at": {"type": "date"},
        }
    }
    _http(
        "PUT", f"{ES_URL}/reviews", json.dumps({"mappings": mappings}).encode(), "application/json"
    )
    for i in range(0, len(reviews), 1000):
        lines = []
        for review in reviews[i : i + 1000]:
            lines.append(json.dumps({"index": {"_index": "reviews", "_id": review["review_id"]}}))
            lines.append(json.dumps(review))
        result = _http(
            "POST",
            f"{ES_URL}/_bulk?refresh=wait_for",
            ("\n".join(lines) + "\n").encode(),
            "application/x-ndjson",
        )
        if result.get("errors"):
            raise SystemExit(f"reviews: Elasticsearch refused a review: {json.dumps(result)[:500]}")


def _cypher(statements: list[tuple[str, dict]]) -> None:
    body = {"statements": [{"statement": s, "parameters": p} for s, p in statements]}
    result = _http(
        "POST", f"{NEO4J_URL}/db/neo4j/tx/commit", json.dumps(body).encode(), "application/json"
    )
    if result.get("errors"):
        raise SystemExit(f"reviews: Neo4j refused a statement: {result['errors']}")


def _seed_neo4j(products: list[dict], customers: list[dict], bought: list[dict]) -> None:
    # One transaction each: Neo4j refuses a schema change in a transaction that has written.
    _cypher([("MATCH (n) DETACH DELETE n", {})])
    for label, key in (("Customer", "customer_id"), ("Product", "product_id")):
        _cypher(
            [
                (
                    f"CREATE CONSTRAINT {key} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE",
                    {},
                )
            ]
        )
    _cypher(
        [
            (
                "UNWIND $rows AS r CREATE (:Product {product_id: r.id, name: r.name, category: r.category})",
                {
                    "rows": [
                        {"id": p["_id"], "name": p["name"], "category": p["category"]}
                        for p in products
                    ]
                },
            )
        ]
    )
    _cypher(
        [
            (
                "UNWIND $rows AS r CREATE (:Customer {customer_id: r.customer_id, name: r.name, "
                "city: r.city, joined: date(r.joined)})",
                {"rows": customers},
            )
        ]
    )
    for i in range(0, len(bought), 2000):
        _cypher(
            [
                (
                    "UNWIND $rows AS r MATCH (c:Customer {customer_id: r.customer_id}) "
                    "MATCH (p:Product {product_id: r.product_id}) CREATE (c)-[:BOUGHT {on: date(r.on)}]->(p)",
                    {"rows": bought[i : i + 2000]},
                )
            ]
        )


def main() -> None:
    if MARKER.exists():
        print("reviews: data already written; nothing to do")
        return
    rng = random.Random(2030)
    products = _catalog(rng)
    customers = _customers(rng)
    bought = _purchases(rng, products)
    by_id = {p["_id"]: p for p in products}
    # A review and a star rating come from a customer who bought the product, after buying it.
    reviewed = rng.sample(bought, REVIEWS)
    reviews = [
        _review(rng, by_id[b["product_id"]], b["customer_id"], n, b["on"])
        for n, b in enumerate(reviewed, start=1)
    ]
    ratings = [
        {
            "product_id": r["product_id"],
            "customer_id": r["customer_id"],
            "stars": r["rating"],
            "rated_at": r["created_at"],
        }
        for r in reviews
    ] + [
        {
            "product_id": b["product_id"],
            "customer_id": b["customer_id"],
            "stars": _review(rng, by_id[b["product_id"]], b["customer_id"], 0, b["on"])["rating"],
            "rated_at": b["on"],
        }
        for b in bought
        if rng.random() < 0.5
    ]
    _seed_mongo(products, ratings)
    _seed_es(reviews)
    _seed_neo4j(products, customers, bought)
    counts = {
        "products": len(products),
        "ratings": len(ratings),
        "reviews": len(reviews),
        "customers": len(customers),
        "purchases": len(bought),
        "battery_dies": sum("battery dies" in r["text"].lower() for r in reviews),
    }
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps(counts))
    print(f"reviews: wrote {counts}")


if __name__ == "__main__":
    main()
