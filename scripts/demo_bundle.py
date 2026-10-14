# Copyright (c) 2026 Kenneth Stott
# Canary: 0a3cf56a-218b-48e7-af83-f7697822fe06
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Build, publish and pull a named demo's bundle (REQ-2049, REQ-2006).

A demo's data is landed once, when its bundle is built -- never at a visitor's request and never
where the demo runs:

``build <name> --out DIR``
    1. the demo's directory is copied to a scratch directory, and its own data stores come up from
       its docker-compose.yml on ports of the build's own, traffic generator (seeder) included --
       the weblogs demo's writes its log files into the copy's ``logs/``; a demo with a
       ``setup.yaml`` is then set up against those stores, by a Provisa server on the demo's own
       config.yaml with a throwaway control plane (scripts/run_demo_setup.py, REQ-2016) -- the
       sonnets demo's embeds its lines into Qdrant and writes its echoes;
    2. a sandbox tier runs on a throwaway embedded control plane in seeding mode
       (``PROVISA_DEMO_SEED_EXPORT=true``): it lands the demo's template from those stores and
       writes the seed -- ``seeded/replicas.duckdb`` and ``seeded/replicas.json``
       (provisa/api/demo_replicas.py);
    3. each Postgres data store (a service labelled ``com.provisa.demo.role: rdb``) is dumped to
       ``dump/<service>.sql``, and each Qdrant store (``com.provisa.demo.role: vector``) is saved as
       one snapshot a collection, ``dump/<service>/<collection>.snapshot``, for the demo's run-time
       compose file (docker-compose.run.yml) to load and restore;
    4. everything is taken down, and the copy is packed (provisa/core/demo_bundles.py) as
       ``DIR/<name>-<version>.tar.gz``, version ``<UTC minute>-<commit>``.

``push BUNDLE``
    publishes it as ``<name>-<version>`` and ``<name>-latest``; a version already published is
    refused. The publisher's credentials are PROVISA_DEMO_REGISTRY_USER and
    PROVISA_DEMO_REGISTRY_TOKEN.

``pull <name>[@<version>] --into DIR``
    unpacks the bundle (``latest`` unless a version is named) into ``DIR/<name>/<version>`` and
    prints that directory. A version already there is not fetched again: a version names one
    bundle forever.

Usage: python scripts/demo_bundle.py build weblogs --out dist/demos
       python scripts/demo_bundle.py push dist/demos/weblogs-202610141530-1a2b3c4d5.tar.gz
       python scripts/demo_bundle.py pull weblogs --into ~/.provisa/demos
"""

# Requirements: REQ-2049, REQ-2006

from __future__ import annotations

import argparse
import datetime
import gzip
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import httpx
import yaml

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from provisa.core import demo_bundles as bundles  # noqa: E402

_NAMED = _REPO / "demo" / "named"
# What a build leaves behind in a demo's directory that is not the demo's: an earlier build's seed
# and dumps, and the seeder's marker volume.
_NOT_COPIED = ("seeded", "dump", "data")
# A small image to hand the stores' files back with (Stores.down).
_CHOWN_IMAGE = "busybox:1.36.1"
_PORT_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*_PORT):-\d+\}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _requires_provisa(demo: Path) -> str:
    spec = yaml.safe_load((demo / "demo.yaml").read_text())
    required = spec.get("requires_provisa")
    if not isinstance(required, str):
        raise SystemExit(f"{demo / 'demo.yaml'}: requires_provisa (the oldest Provisa it runs on)")
    bundles.provisa_version_key(required)
    return required


def _copy(demo: Path, work: Path) -> Path:
    copy = work / "named" / demo.name
    shutil.copytree(demo, copy, ignore=lambda d, _names: _NOT_COPIED if Path(d) == demo else ())
    # Logs a development run left: the build's seeder writes the bundle's own.
    logs = copy / "logs"
    if logs.is_dir():
        for path in logs.rglob("*"):
            if path.is_file() and path.name != ".gitignore":
                path.unlink()
    return copy


class Stores:
    """The demo's data stores, under a compose project of the build's own, on its own ports."""

    def __init__(self, demo: Path) -> None:
        self.demo = demo
        self.compose_file = demo / "docker-compose.yml"
        self.project = f"provisa-demo-bundle-{demo.name}-{os.getpid()}"
        text = self.compose_file.read_text() if self.compose_file.exists() else ""
        self.ports = {name: str(_free_port()) for name in sorted(set(_PORT_VAR.findall(text)))}
        self.env = {**os.environ, "PROVISA_NAMED_DEMO_DIR": str(demo), **self.ports}

    def _compose(self, *args: str, **kw) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-p", self.project, "-f", str(self.compose_file), *args]
        return subprocess.run(cmd, env=self.env, check=True, **kw)

    def up(self) -> None:
        if not self.compose_file.exists():
            return
        self._compose("up", "-d", "--build", "--wait", "--scale", "seeder=0")
        services = self._compose("config", "--services", capture_output=True, text=True)
        if "seeder" in services.stdout.split():
            # Once, to its end, with the stores it writes to left running; its exit fails the build.
            self._compose("run", "--rm", "--no-deps", "seeder")

    def dump(self) -> list[str]:
        """Each Postgres data store's database, to dump/<service>.sql."""
        if not self.compose_file.exists():
            return []
        config = json.loads(
            self._compose("config", "--format", "json", capture_output=True, text=True).stdout
        )
        dumped = []
        for name, service in sorted(config["services"].items()):
            labels = service.get("labels") or {}
            if labels.get("com.provisa.demo.role") == "vector":
                dumped += self._snapshot(name, service)
                continue
            if labels.get("com.provisa.demo.role") != "rdb":
                continue
            if not str(service["image"]).startswith("postgres:"):
                raise SystemExit(f"{self.demo.name}: data store {name} is not Postgres; no dump")
            env = service["environment"]
            target = self.demo / "dump" / f"{name}.sql"
            target.parent.mkdir(exist_ok=True)
            with target.open("w") as out:
                self._compose(
                    "exec",
                    "-T",
                    name,
                    "pg_dump",
                    "-U",
                    env["POSTGRES_USER"],
                    "--no-owner",
                    "--no-acl",
                    env["POSTGRES_DB"],
                    stdout=out,
                )
            dumped.append(name)
        return dumped

    def _snapshot(self, name: str, service: dict) -> list[str]:
        """Each collection of Qdrant store ``name``, as a snapshot in dump/<name>/<collection>.snapshot
        (REQ-2016): what it holds is read live where the demo runs, restored from these."""
        if not str(service["image"]).startswith("qdrant/qdrant:"):
            raise SystemExit(f"{self.demo.name}: vector store {name} is not Qdrant; no snapshot")
        published = self._compose("port", name, "6333", capture_output=True, text=True).stdout
        base = f"http://127.0.0.1:{published.strip().rsplit(':', 1)[1]}"
        collections = httpx.get(f"{base}/collections", timeout=60)
        collections.raise_for_status()
        saved = []
        for collection in sorted(c["name"] for c in collections.json()["result"]["collections"]):
            made = httpx.post(f"{base}/collections/{collection}/snapshots", timeout=600)
            made.raise_for_status()
            snapshot = made.json()["result"]["name"]
            target = self.demo / "dump" / name / f"{collection}.snapshot"
            target.parent.mkdir(parents=True, exist_ok=True)
            with httpx.stream(
                "GET", f"{base}/collections/{collection}/snapshots/{snapshot}", timeout=600
            ) as fetched:
                fetched.raise_for_status()
                with target.open("wb") as out:
                    for chunk in fetched.iter_bytes():
                        out.write(chunk)
            saved.append(f"{name}/{collection}")
        return saved

    def down(self) -> None:
        if not self.compose_file.exists():
            return
        self._compose("down", "--volumes", "--remove-orphans")
        # What the stores' containers wrote into the copy (the seeder's marker, the log files) is
        # root's on Linux: given back to this user, so it can be packed and the copy removed.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.demo}:/demo",
                _CHOWN_IMAGE,
                "chown",
                "-R",
                f"{os.getuid()}:{os.getgid()}",
                "/demo",
            ],
            check=True,
        )


def _control_plane(work: Path, name: str = "cp") -> tuple[str, str]:
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "provisa.core.control_plane_pg",
            "start",
            str(work / name),
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
                    "jwt_secret": "demo-bundle-build-only-secret-not-a-deployment",
                    "assignments_source": "provisa",
                },
                "naming": {"domain_prefix": False, "rules": []},
                "cache": {"enabled": False},
                "domains": [{"id": "ops", "description": "the bundle build's own"}],
                "roles": [],
                "sources": [],
                "tables": [],
            }
        )
    )
    return path


def _set_up(work: Path, demo: Path, stores: Stores, timeout: float) -> None:
    """Run the demo's setup.yaml against its running stores (REQ-2016): a Provisa server on the
    demo's own config.yaml, with a throwaway control plane of its own, set up by
    scripts/run_demo_setup.py -- what its commands write is then in the stores the build dumps."""
    host, port = _control_plane(work, "setup-cp")
    url = f"postgresql+psycopg://provisa:provisa@/provisa?host={host}&port={port}"
    http_port = _free_port()
    server_env = {
        **stores.env,
        "PROVISA_CONFIG": str(demo / "config.yaml"),
        "PROVISA_ENGINE": "duckdb",
        "PROVISA_DATA_DIR": str(work / "setup-data"),
        "PROVISA_REDIS_EMBEDDED": "1",
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
    base = f"http://127.0.0.1:{http_port}"
    try:
        deadline = time.monotonic() + timeout
        while True:
            if server.poll() is not None:
                raise SystemExit(f"the setup server exited early ({server.returncode})")
            try:
                if httpx.get(f"{base}/health", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass  # not listening yet; the deadline below bounds the wait
            if time.monotonic() > deadline:
                raise SystemExit(f"{demo.name}: the setup server was not up in {timeout:.0f}s")
            time.sleep(2)
        subprocess.run(
            [sys.executable, str(_REPO / "scripts" / "run_demo_setup.py"), str(demo)]
            + ["--url", base],
            check=True,
        )
    finally:
        server.terminate()
        server.wait(timeout=60)
        subprocess.run(
            [sys.executable, "-m", "provisa.core.control_plane_pg", "stop", str(work / "setup-cp")],
            check=True,
        )


def _seed(work: Path, demo: Path, stores: Stores, timeout: float) -> None:
    """Land the demo's template from its running stores and write its seed into ``demo``."""
    host, port = _control_plane(work)
    url = f"postgresql+psycopg://provisa:provisa@/provisa?host={host}&port={port}"
    http_port = _free_port()
    server_env = {
        **stores.env,
        "ORG_ID": "demobundle",
        "PROVISA_CONFIG": str(_config(work)),
        "PROVISA_ENGINE": "duckdb",
        "PROVISA_SANDBOX_TIER": "true",
        "PROVISA_DEMO_SEED_EXPORT": "true",
        "PROVISA_NAMED_DEMOS_DIR": str(demo.parent),
        "PROVISA_DATA_DIR": str(work / "data"),
        "PROVISA_REDIS_EMBEDDED": "1",
        "PROVISA_LOGS_ALLOWED_ROOTS": str(demo / "logs"),
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
    record = demo / "seeded" / "replicas.json"
    try:
        deadline = time.monotonic() + timeout
        while not record.exists():
            if server.poll() is not None:
                raise SystemExit(f"the seeding run exited early ({server.returncode})")
            if time.monotonic() > deadline:
                raise SystemExit(f"{demo.name} not seeded in {timeout:.0f}s")
            time.sleep(2)
        httpx.get(f"http://127.0.0.1:{http_port}/health", timeout=10).raise_for_status()
    finally:
        server.terminate()
        server.wait(timeout=60)
        subprocess.run(
            [sys.executable, "-m", "provisa.core.control_plane_pg", "stop", str(work / "cp")],
            check=True,
        )


def _replicates(demo: Path, stores: Stores) -> bool:
    """Whether the demo serves any table from a replica, which its seed lands (REQ-2049): a demo's
    own sources are read live where it runs, so a demo of only those has no seed to write."""
    from provisa.api.demo_templates import replicated_tables
    from provisa.core.config_loader import parse_config_dict, read_config_with_includes

    saved = dict(os.environ)
    os.environ.update({k: v for k, v in stores.env.items() if k not in saved or saved[k] != v})
    try:
        config = parse_config_dict(read_config_with_includes(demo / "config.yaml"))
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return bool(replicated_tables(config))


def _commit() -> str:
    return subprocess.run(
        ["git", "-C", str(_REPO), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def build(args: argparse.Namespace) -> int:
    source = (args.named_dir / args.name).resolve()
    if not (source / "demo.yaml").exists():
        raise SystemExit(f"no named demo {args.name} in {args.named_dir}")
    requires = _requires_provisa(source)
    commit = args.commit or _commit()
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M")
    manifest = bundles.BundleManifest(args.name, f"{stamp}-{commit[:9]}", commit, requires)
    with tempfile.TemporaryDirectory(prefix="provisa-demo-bundle-") as scratch:
        work = Path(scratch)
        demo = _copy(source, work)
        stores = Stores(demo)
        try:
            stores.up()
            if (demo / "setup.yaml").exists():
                _set_up(work, demo, stores, args.timeout)
            if _replicates(demo, stores):
                _seed(work, demo, stores, args.timeout)
            dumped = stores.dump()
        finally:
            stores.down()
        bundle = bundles.pack(demo, manifest)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.name}-{manifest.version}.tar.gz"
    path.write_bytes(bundle)
    print(f"built {path} ({len(bundle)} bytes; dumps: {', '.join(dumped) or 'none'})")
    return 0


def _manifest_in(bundle: bytes) -> bundles.BundleManifest:
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(bundle)), mode="r") as tar:
        member = tar.extractfile(bundles.MANIFEST_FILE)
        if member is None:
            raise SystemExit(f"the bundle has no {bundles.MANIFEST_FILE}")
        return bundles.BundleManifest.read(json.load(member))


def push(args: argparse.Namespace) -> int:
    bundle = args.bundle.read_bytes()
    manifest = _manifest_in(bundle)
    user, token = (
        os.environ["PROVISA_DEMO_REGISTRY_USER"],
        os.environ["PROVISA_DEMO_REGISTRY_TOKEN"],
    )
    digest = bundles.Registry(args.registry, credentials=(user, token)).push(manifest, bundle)
    print(
        f"published {manifest.demo} {manifest.version} as "
        f"{bundles.tag_of(manifest.demo, manifest.version)} and "
        f"{bundles.tag_of(manifest.demo, bundles.LATEST)} ({digest})"
    )
    return 0


def pull(args: argparse.Namespace) -> int:
    print(bundles.pull_into(args.spec, args.into, args.registry))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A named demo's bundle (REQ-2049).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build a demo's bundle")
    b.add_argument("name")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--named-dir", type=Path, default=_NAMED)
    b.add_argument("--commit", help="the commit built (default: this checkout's HEAD)")
    b.add_argument("--timeout", type=float, default=1800.0)
    p = sub.add_parser("push", help="publish a built bundle")
    p.add_argument("bundle", type=Path)
    p.add_argument("--registry", default=bundles.PUBLISHED_AT)
    q = sub.add_parser("pull", help="pull a demo's bundle and print its directory")
    q.add_argument("spec", help="<name> or <name>@<version>")
    q.add_argument("--into", type=Path, required=True)
    # Where the project publishes, unless PROVISA_DEMO_REGISTRY names another (as the sandbox
    # tier and start-ui-install.sh are told).
    q.add_argument(
        "--registry", default=os.environ.get("PROVISA_DEMO_REGISTRY", bundles.PUBLISHED_AT)
    )
    args = parser.parse_args(argv)
    try:
        return {"build": build, "push": push, "pull": pull}[args.command](args)
    except bundles.BundleError as refused:
        print(f"ERROR: {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
