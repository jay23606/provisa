# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Seed every published named demo, for the image the release builds (REQ-2006).

A demo's data is landed here, once, when the release is built -- never at a visitor's request and
never on the deployment. For each published demo (``published: true`` in its demo.yaml):

1. its own data stores come up -- its docker-compose.yml, when it has one, traffic generator
   included (the weblogs demo's writes its log files into the demo's ``logs/`` here);
2. a sandbox tier runs on a throwaway embedded control plane in seeding mode
   (``PROVISA_DEMO_SEED_EXPORT=true``): it lands each demo's template from those stores and
   writes the demo's seed beside its demo.yaml -- ``seeded/replicas.duckdb`` and
   ``seeded/replicas.json`` (provisa/api/demo_replicas.py);
3. everything is taken down again.

The Dockerfile then copies the demos, seeds and generated logs included, into the image, and a
deployment's sandbox tier lands each template from its seed: no demo's data store runs there.

Usage: python scripts/build_demo_seeds.py [--named-dir DIR] [--timeout SECONDS]
"""

# Requirements: REQ-2006

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

_REPO = Path(__file__).resolve().parents[1]
_NAMED = _REPO / "demo" / "named"


def _published(named: Path) -> list[Path]:
    found = []
    for spec in sorted(named.glob("*/demo.yaml")):
        published = yaml.safe_load(spec.read_text()).get("published")
        if not isinstance(published, bool):
            raise SystemExit(f"{spec}: published must be true or false")
        if published:
            found.append(spec.parent)
    return found


def _compose(demo: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        f"provisa-demo-seed-{demo.name}",
        "-f",
        str(demo / "docker-compose.yml"),
        *args,
    ]


def _stores_up(demo: Path, env: dict[str, str]) -> None:
    """The demo's data stores, up, and its seeder (traffic generator) finished."""
    if not (demo / "docker-compose.yml").exists():
        return
    subprocess.run(_compose(demo, "up", "-d", "--build", "--wait"), env=env, check=True)
    services = subprocess.run(
        _compose(demo, "config", "--services"), env=env, check=True, capture_output=True, text=True
    ).stdout.split()
    if "seeder" in services:
        subprocess.run(_compose(demo, "wait", "seeder"), env=env, check=True)


def _stores_down(demo: Path, env: dict[str, str]) -> None:
    if (demo / "docker-compose.yml").exists():
        subprocess.run(_compose(demo, "down", "--volumes"), env=env, check=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _control_plane(work: Path) -> tuple[str, str]:
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "provisa.core.control_plane_pg",
            "start",
            str(work / "cp"),
            "--init-sql",
            str(_REPO / "db" / "init.sql"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    found = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return found["PG_HOST"], found["PG_PORT"]


def _config(work: Path) -> Path:
    path = work / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "federation_engine": "duckdb",
                "multitenancy": True,
                "auth": {
                    "provider": "basic",
                    "jwt_secret": "demo-seed-build-only-secret-not-a-deployment",
                    "assignments_source": "provisa",
                },
                "naming": {"domain_prefix": False, "rules": []},
                "cache": {"enabled": False},
                "domains": [{"id": "ops", "description": "the seeding run's own"}],
                "roles": [],
                "sources": [],
                "tables": [],
            }
        )
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed every published named demo (REQ-2006).")
    parser.add_argument("--named-dir", type=Path, default=_NAMED, help="where the named demos are")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()
    named = args.named_dir.resolve()
    demos = _published(named)
    if not demos:
        print("no published demo to seed")
        return 0
    with tempfile.TemporaryDirectory(prefix="provisa-demo-seed-") as scratch:
        work = Path(scratch)
        env = {**os.environ}
        for demo in demos:
            (demo / "seeded" / "replicas.json").unlink(missing_ok=True)
            env_demo = {**env, "PROVISA_NAMED_DEMO_DIR": str(demo)}
            _stores_up(demo, env_demo)
        host, port = _control_plane(work)
        url = f"postgresql+psycopg://provisa:provisa@/provisa?host={host}&port={port}"
        http_port = _free_port()
        server_env = {
            **env,
            "ORG_ID": "demoseeding",
            "PROVISA_CONFIG": str(_config(work)),
            "PROVISA_ENGINE": "duckdb",
            "PROVISA_SANDBOX_TIER": "true",
            "PROVISA_DEMO_SEED_EXPORT": "true",
            "PROVISA_NAMED_DEMOS_DIR": str(named),
            "PROVISA_DATA_DIR": str(work / "data"),
            "PROVISA_REDIS_EMBEDDED": "1",
            "PROVISA_LOGS_ALLOWED_ROOTS": ",".join(str(d / "logs") for d in demos),
            "TENANT_DATABASE_URL": url,
            "PLATFORM_DATABASE_URL": url,
            "PG_HOST": host,
            "PG_PORT": port,
            "OTEL_SDK_DISABLED": "true",
        }
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(http_port),
            ],
            cwd=_REPO,
            env=server_env,
        )
        try:
            deadline = time.monotonic() + args.timeout
            pending = {d for d in demos}
            while pending:
                if server.poll() is not None:
                    raise SystemExit(f"the seeding run exited early ({server.returncode})")
                if time.monotonic() > deadline:
                    raise SystemExit(
                        f"not seeded in {args.timeout:.0f}s: {sorted(d.name for d in pending)}"
                    )
                pending = {d for d in pending if not (d / "seeded" / "replicas.json").exists()}
                time.sleep(2)
            httpx.get(f"http://127.0.0.1:{http_port}/health", timeout=10)
        finally:
            server.terminate()
            server.wait(timeout=60)
            subprocess.run(
                [sys.executable, "-m", "provisa.core.control_plane_pg", "stop", str(work / "cp")],
                check=True,
            )
            for demo in demos:
                _stores_down(demo, {**env, "PROVISA_NAMED_DEMO_DIR": str(demo)})
    for demo in demos:
        print(f"seeded {demo.name}: {demo / 'seeded'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
