# Copyright (c) 2026 Kenneth Stott
# Canary: d14457c2-7194-4bf7-8281-1a1dda7ea747
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Write the quality demo's sales feed, db/incoming.tsv (REQ-2051): two daily batches from a chain
of five shops, as they are delivered.

The well-formed fields (sale id, when sold, quantity) arrive clean. Three arrive messy as any feed
does, and silver cleans them: the shop code in any case with stray spaces (" s-01"), the product
in many spellings ("COFFEE", "cofee", "muffins"), the price with or without a dollar sign or its
second decimal ("$4.50", "4.5"). A few sales are sent twice, the later line correcting the first.

Batch 1 (2026-10-01) is clean once cleaned. Batch 2 (2026-10-02) carries what no cleaning fixes:
sales from a shop the chain does not have, negative quantities and prices that are not numbers.
Deterministic (seed 2051), so the committed file is what this writes.

Usage: python demo/named/quality/generate.py
"""

from __future__ import annotations

import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORES = ["S-01", "S-02", "S-03", "S-04", "S-05"]
# Each product's price and the spellings it is delivered in.
PRODUCTS = {
    "coffee": (4.50, ["coffee", "Coffee", "COFFEE", "cofee"]),
    "tea": (3.20, ["tea", "Tea", "TEA"]),
    "muffin": (2.75, ["muffin", "Muffin", "muffins"]),
    "sandwich": (7.90, ["sandwich", "Sandwich", "sandwhich"]),
    "juice": (3.95, ["juice", "Juice", "JUICE"]),
}
PER_BATCH = 120


def _store(rng: random.Random) -> str:
    code = rng.choice(STORES)
    return rng.choice([code, code.lower(), f" {code}", f"{code} "])


def _price(rng: random.Random, price: float) -> str:
    return rng.choice([f"{price:.2f}", f"${price:.2f}", f"{price:g}"])


def _sales(rng: random.Random, batch: int, day: str, first_id: int) -> list[list[str]]:
    rows = []
    for i in range(PER_BATCH):
        product = rng.choice(sorted(PRODUCTS))
        price, spellings = PRODUCTS[product]
        hour, minute = rng.randint(7, 19), rng.randint(0, 59)
        rows.append(
            [
                str(batch),
                f"T{first_id + i:06d}",
                _store(rng),
                rng.choice(spellings),
                f"{day} {hour:02d}:{minute:02d}:00",
                str(rng.randint(1, 4)),
                _price(rng, price),
            ]
        )
    # A few sales sent again later in the batch, the resend correcting the quantity.
    for row in rows[5:8]:
        rows.append([*row[:5], str(int(row[5]) + 1), row[6]])
    return rows


def main() -> None:
    rng = random.Random(2051)
    good = _sales(rng, 1, "2026-10-01", 1)
    bad = _sales(rng, 2, "2026-10-02", PER_BATCH + 1)
    for row in bad[0:3]:
        row[2] = "S-99"  # a shop the chain does not have
    for row in bad[10:12]:
        row[5] = "-" + row[5]  # a negative quantity
    bad[20][6] = "4,50"  # a price that is not a number
    bad[21][6] = "n/a"
    lines = ["\t".join(row) for row in good + bad]
    (HERE / "db" / "incoming.tsv").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
