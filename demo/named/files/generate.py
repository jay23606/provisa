# Copyright (c) 2026 Kenneth Stott
# Canary: eeccfb63-6a7c-4915-af4e-d44f4f18a5e2
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The files demo's open-data drop (REQ-2032): a small city's files, generated from a fixed seed so
every build writes the same ones into data/. The city, its streets and its people are invented.

    complaints_2026_08.csv, complaints_2026_09.csv  311 complaints, one file a month
    building_permits.parquet                        building permits
    budget_2026.xlsx                                the city budget, a line a department and area
    inspections.json                                inspections of permitted work

Usage: python generate.py <out dir>
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import random
import sys
from pathlib import Path

NEIGHBORHOODS = ["Riverside", "Old Town", "Millbrook", "Harbor Point", "Cedar Heights", "Eastgate"]
STREETS = {
    "Riverside": ["River Rd", "Willow Ln", "Bank St"],
    "Old Town": ["Market St", "Church St", "Mill Ln"],
    "Millbrook": ["Brook Ave", "Mill Rd", "Elm St"],
    "Harbor Point": ["Harbor Blvd", "Dock St", "Pier Ave"],
    "Cedar Heights": ["Cedar Dr", "Summit Ave", "Ridge Rd"],
    "Eastgate": ["East Ave", "Gate St", "Orchard Ln"],
}
# How much is being built where: the busier a neighborhood, the more permits and the more noise.
BUILDING = {
    "Riverside": 3,
    "Old Town": 1,
    "Millbrook": 2,
    "Harbor Point": 5,
    "Cedar Heights": 1,
    "Eastgate": 4,
}
CATEGORIES = ["Noise", "Street condition", "Dust", "Blocked sidewalk", "Trash", "Streetlight"]
DEPARTMENTS = ["Public Works", "Parks", "Planning", "Sanitation", "Transportation"]


def _address(rng: random.Random, area: str) -> str:
    return f"{rng.randint(1, 240)} {rng.choice(STREETS[area])}"


def _permits(rng: random.Random) -> list[dict]:
    rows, n = [], 0
    for area, weight in BUILDING.items():
        for _ in range(weight * 8):
            n += 1
            issued = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randint(0, 240))
            expires = issued + dt.timedelta(days=rng.choice([90, 180, 365]))
            rows.append(
                {
                    "permit_id": f"BP-{n:04d}",
                    "address": _address(rng, area),
                    "neighborhood": area,
                    "permit_type": rng.choice(
                        ["New building", "Addition", "Demolition", "Renovation"]
                    ),
                    "issued_on": issued,
                    "expires_on": expires,
                    "status": "active" if expires >= dt.date(2026, 9, 1) else "expired",
                    "valuation": rng.randint(20, 900) * 1000,
                }
            )
    return rows


def _complaints(rng: random.Random, month: int, start_id: int, permits: list[dict]) -> list[dict]:
    rows = []
    active = [p for p in permits if p["status"] == "active"]
    for i in range(300):
        area = rng.choices(NEIGHBORHOODS, weights=[1 + BUILDING[a] for a in NEIGHBORHOODS])[0]
        near = [p for p in active if p["neighborhood"] == area]
        construction = near and rng.random() < 0.5
        category = (
            rng.choice(["Noise", "Dust", "Blocked sidewalk"])
            if construction
            else rng.choice(CATEGORIES)
        )
        address = rng.choice(near)["address"] if construction else _address(rng, area)
        opened = dt.datetime(2026, month, 1) + dt.timedelta(minutes=rng.randint(0, 29 * 24 * 60))
        closed = rng.random() < 0.6
        rows.append(
            {
                "complaint_id": start_id + i,
                "opened_at": opened.isoformat(timespec="minutes"),
                "status": "closed" if closed else "open",
                "closed_at": (opened + dt.timedelta(days=rng.randint(1, 20))).isoformat(
                    timespec="minutes"
                )
                if closed
                else "",
                "category": category,
                "neighborhood": area,
                "address": address,
            }
        )
    return rows


def main(out: Path) -> None:
    import pandas as pd

    rng = random.Random(2032)
    out.mkdir(parents=True, exist_ok=True)
    permits = _permits(rng)
    pd.DataFrame(permits).to_parquet(out / "building_permits.parquet", index=False)
    for month, start in ((8, 10001), (9, 20001)):
        rows = _complaints(rng, month, start, permits)
        with (out / f"complaints_2026_{month:02d}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    budget = [
        {"neighborhood": area, "department": dept, "amount": rng.randint(50, 900) * 1000}
        for area in NEIGHBORHOODS
        for dept in DEPARTMENTS
    ]
    pd.DataFrame(budget).to_excel(out / "budget_2026.xlsx", sheet_name="budget", index=False)
    inspections = []
    for i, permit in enumerate(rng.sample(permits, 60), start=1):
        inspections.append(
            {
                "inspection_id": i,
                "permit_id": permit["permit_id"],
                "inspected_on": (
                    permit["issued_on"] + dt.timedelta(days=rng.randint(5, 60))
                ).isoformat(),
                "result": rng.choice(["passed", "passed", "failed", "corrections needed"]),
            }
        )
    (out / "inspections.json").write_text(json.dumps(inspections, indent=1) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
