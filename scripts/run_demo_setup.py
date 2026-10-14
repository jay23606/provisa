#!/usr/bin/env python3
# Copyright (c) 2026 Kenneth Stott
# Canary: 54021000-9413-4f46-8a92-1a98b4c2425f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""Run a named demo's setup.yaml once against a running server (REQ-2016).

A demo's setup.yaml lists, in order, what it needs run after the server is up: ``command: <name>``
calls a command of its config.yaml as org_admin with no arguments; ``refresh: <view>`` builds the
stored rows of a view of its config.yaml with ``materialize: true``. start-ui-install.sh and the
demo's template build both call this, so the two set a demo up alike.

Once per control plane: the demo's name is added to the operator setting ``demo.setup_completed``
when every step has succeeded, and a demo already listed there is not set up again. The first step
that fails stops the run: the exit status is 1 and the step is named. Nothing is retried.

Usage: run_demo_setup.py <demo dir> --url <server base url>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

SETTING = "demo.setup_completed"
_ROLE = {"X-Provisa-Role": "org_admin"}
_TIMEOUT = 1800.0


class StepFailed(RuntimeError):
    def __init__(self, step: dict, why: str) -> None:
        super().__init__(f"setup step {step} failed: {why}")


def steps(demo_dir: Path) -> list[dict]:
    """The demo's steps, each one ``command`` or one ``refresh``; none when it has no setup.yaml."""
    path = demo_dir / "setup.yaml"
    if not path.exists():
        return []
    listed = (yaml.safe_load(path.read_text()) or {}).get("steps") or []
    for step in listed:
        if (
            not isinstance(step, dict)
            or len(step) != 1
            or next(iter(step))
            not in (
                "command",
                "refresh",
            )
        ):
            raise SystemExit(
                f"{path}: a step is one 'command: <name>' or 'refresh: <view>': {step}"
            )
    return listed


def _ok(response: httpx.Response, step: dict) -> Any:
    if response.status_code != 200:
        raise StepFailed(step, f"HTTP {response.status_code}: {response.text}")
    body = response.json()
    if body.get("errors"):
        raise StepFailed(step, "; ".join(e.get("message", str(e)) for e in body["errors"]))
    return body.get("data")


def completed(client: httpx.Client) -> list[str]:
    response = client.get("/admin/settings/catalog")
    response.raise_for_status()
    for card in response.json()["cards"]:
        for setting in card["settings"]:
            if setting["key"] == SETTING:
                return list(setting["value"] or [])
    raise SystemExit(f"the server has no setting {SETTING}")


def _mutation_field(client: httpx.Client, command: str, step: dict) -> tuple[str, str | None]:
    """The GraphQL mutation field of ``command`` (its name in the active naming convention, under
    its domain's prefix when there is one) and a field of its result to select, if it has fields."""
    data = _ok(
        client.post(
            "/data/graphql",
            json={
                "query": "{ __schema { mutationType { fields { name type { kind name ofType "
                "{ kind name ofType { kind name ofType { kind name } } } } } } } }"
            },
        ),
        step,
    )
    wanted = command.replace("_", "").lower()
    found = [
        f
        for f in data["__schema"]["mutationType"]["fields"]
        if f["name"].rsplit("__", 1)[-1].replace("_", "").lower() == wanted
    ]
    if len(found) != 1:
        raise StepFailed(step, f"the server has {len(found)} mutations for command {command!r}")
    named = found[0]["type"]
    while named.get("ofType"):
        named = named["ofType"]
    selection = None
    if named["kind"] == "OBJECT":
        fields = _ok(
            client.post(
                "/data/graphql",
                json={"query": f'{{ __type(name: "{named["name"]}") {{ fields {{ name }} }} }}'},
            ),
            step,
        )["__type"]["fields"]
        selection = fields[0]["name"]
    return found[0]["name"], selection


def run_step(client: httpx.Client, step: dict) -> str:
    """Run one step; what it did, for the log."""
    if "command" in step:
        field, selection = _mutation_field(client, step["command"], step)
        query = f"mutation {{ {field}{f' {{ {selection} }}' if selection else ''} }}"
        data = _ok(client.post("/data/graphql", json={"query": query}), step)
        return f"command {step['command']}: {data[field]}"
    view = step["refresh"]
    data = _ok(
        client.post(
            "/admin/graphql",
            json={
                "query": f'mutation {{ refreshMv(mvId: "view-view_{view}") {{ success message }} }}'
            },
        ),
        step,
    )
    if not data["refreshMv"]["success"]:
        raise StepFailed(step, data["refreshMv"]["message"])
    return f"refresh {view}: {data['refreshMv']['message']}"


def run(demo_dir: Path, url: str) -> int:
    listed = steps(demo_dir)
    if not listed:
        return 0
    name = demo_dir.resolve().name
    with httpx.Client(base_url=url, headers=_ROLE, timeout=_TIMEOUT) as client:
        done = completed(client)
        if name in done:
            print(f"demo {name}: already set up ({SETTING}); nothing to run")
            return 0
        for step in listed:
            try:
                print(f"demo {name}: {run_step(client, step)}", flush=True)
            except StepFailed as failed:
                print(f"demo {name}: {failed}", file=sys.stderr)
                return 1
        stored = client.put(
            "/admin/settings/catalog", json={"values": {SETTING: [*done, name]}, "confirm": []}
        )
        stored.raise_for_status()
    print(f"demo {name}: set up")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("demo_dir", type=Path)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    sys.exit(run(args.demo_dir, args.url))
