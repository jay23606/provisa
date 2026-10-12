# Copyright (c) 2026 Kenneth Stott
# Canary: b7d08db5-6aee-4f66-b500-cf9bb1f3597f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""On-demand, pinned, hash-checked JavaScript runtimes for Node sources (REQ-1984).

A Node source names its runtime: Node, Bun or Deno. None of them ships with Provisa. Each is
fetched on first use from its project's own release, at the version pinned here, checked against
the SHA-256 recorded here (the project's published sum) BEFORE anything is extracted, and cached
under the runtime-deps cache root beside the pgwire bundles, version-namespaced. A cache hit never
downloads.

Resolution fails loud: an unknown runtime, a platform with no pinned archive, a download that
fails, an archive whose hash is not the recorded one, or an archive without the runtime's
executable raises ``RuntimeUnavailable``. There is no unpinned or unchecked fallback.
"""

# Requirements: REQ-1984
from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Callable

from provisa.runtime_deps.pgwire_bundles import default_cache_root

#: The release platforms Provisa runs on (the same three the pgwire bundles are built for).
DARWIN_ARM64 = ("Darwin", "arm64")
LINUX_X64 = ("Linux", "x86_64")
WINDOWS_X64 = ("Windows", "AMD64")


class RuntimeUnavailable(Exception):  # REQ-1984
    """A JavaScript runtime could not be resolved; never a fallback."""


@dataclass(frozen=True)
class Asset:
    """One platform's archive of a pinned runtime release."""

    filename: str
    #: The project's published SHA-256 of ``filename``.
    sha256: str
    #: The runtime's executable, relative to the extracted archive's root.
    executable: str


@dataclass(frozen=True)
class RuntimePin:
    name: str
    version: str
    #: ``{version}`` and ``{filename}`` are filled in.
    url_template: str
    assets: dict[tuple[str, str], Asset]

    def asset(self, key: tuple[str, str] | None = None) -> Asset:
        key = key or (platform.system(), platform.machine())
        found = self.assets.get(key)
        if found is None:
            raise RuntimeUnavailable(
                f"no {self.name} {self.version} is pinned for {key[0]}/{key[1]}"
            )
        return found

    def url(self, asset: Asset) -> str:
        return self.url_template.format(version=self.version, filename=asset.filename)


# The pinned releases. A bump changes the version and every sum together; each sum is the one the
# project publishes (Node: SHASUMS256.txt; Bun: the release's SHASUMS256.txt; Deno: the asset's
# .sha256sum).
RUNTIMES: dict[str, RuntimePin] = {
    "node": RuntimePin(
        "node",
        "24.21.0",
        "https://nodejs.org/dist/v{version}/{filename}",
        {
            DARWIN_ARM64: Asset(
                "node-v24.21.0-darwin-arm64.tar.gz",
                "bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057",
                "node-v24.21.0-darwin-arm64/bin/node",
            ),
            LINUX_X64: Asset(
                "node-v24.21.0-linux-x64.tar.gz",
                "6e1db87ef58b8819e5d5402eff1536491b18edd8eb7bee5ef7897876e88dc5ff",
                "node-v24.21.0-linux-x64/bin/node",
            ),
            WINDOWS_X64: Asset(
                "node-v24.21.0-win-x64.zip",
                "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
                "node-v24.21.0-win-x64/node.exe",
            ),
        },
    ),
    "bun": RuntimePin(
        "bun",
        "1.4.2",
        "https://github.com/oven-sh/bun/releases/download/bun-v{version}/{filename}",
        {
            DARWIN_ARM64: Asset(
                "bun-darwin-aarch64.zip",
                "90987a3a16d7db556d886ac3d551e7b6d3edf0a1cf43acaed622e8676be1d12f",
                "bun-darwin-aarch64/bun",
            ),
            LINUX_X64: Asset(
                "bun-linux-x64.zip",
                "36368faef7527875d5ffa52e53cd48021741f2a83eb6208a8dd64068d422a913",
                "bun-linux-x64/bun",
            ),
            WINDOWS_X64: Asset(
                "bun-windows-x64.zip",
                "ce4c17497b2f29712a99d3d53f028de28cd42e3bacb8589599e7f000e49b6405",
                "bun-windows-x64/bun.exe",
            ),
        },
    ),
    "deno": RuntimePin(
        "deno",
        "2.9.7",
        "https://github.com/denoland/deno/releases/download/v{version}/{filename}",
        {
            DARWIN_ARM64: Asset(
                "deno-aarch64-apple-darwin.zip",
                "5cd46d6268f6f78f5d88bdc7159d20bd44cdaa4b3303474839f87ec6fe7ae25c",
                "deno",
            ),
            LINUX_X64: Asset(
                "deno-x86_64-unknown-linux-gnu.zip",
                "c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490",
                "deno",
            ),
            WINDOWS_X64: Asset(
                "deno-x86_64-pc-windows-msvc.zip",
                "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238",
                "deno.exe",
            ),
        },
    ),
}

#: Fetch an archive's bytes. Injected so tests never touch the network.
Fetcher = Callable[[str], bytes]


def fetch_https(url: str) -> bytes:
    """The archive at ``url``, over https only. Fails loud on any error."""
    import httpx

    if not url.startswith("https://"):
        raise RuntimeUnavailable(f"refusing a non-https runtime URL: {url}")
    try:
        response = httpx.get(url, follow_redirects=True, timeout=300.0)
    except httpx.HTTPError as exc:
        raise RuntimeUnavailable(f"failed to download {url}: {exc}") from exc
    if response.status_code != HTTPStatus.OK:
        raise RuntimeUnavailable(f"failed to download {url}: HTTP {response.status_code}")
    return response.content


def _extract(filename: str, data: bytes, dest: Path) -> None:
    """Expand ``data`` under ``dest``, refusing any entry that escapes it."""
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = dest.resolve()
            for info in archive.infolist():
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(root):
                    raise RuntimeUnavailable(
                        f"{filename}: entry escapes the archive: {info.filename}"
                    )
            # Every entry was checked above to land inside dest.
            archive.extractall(dest)  # nosec B202
        return
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(dest, filter="data")  # nosec B202 - the "data" filter refuses every unsafe member


class JsRuntimeResolver:  # REQ-1984
    """Resolves a runtime name to its cached executable, downloading and checking on a miss.

    Caches under ``<cache_root>/js/<name>/<version>/``; the executable's presence there is the
    marker of a complete resolution, because a resolution is extracted to a staging directory and
    moved into place whole."""

    def __init__(
        self,
        *,
        cache_root: str | Path | None = None,
        fetcher: Fetcher | None = None,
        host: tuple[str, str] | None = None,
    ) -> None:
        self._root = Path(cache_root) if cache_root is not None else default_cache_root()
        self._fetch = fetcher if fetcher is not None else fetch_https
        self._host = host

    def pin(self, name: str) -> RuntimePin:
        pin = RUNTIMES.get(name)
        if pin is None:
            raise RuntimeUnavailable(f"{name!r} is not a runtime (known: {sorted(RUNTIMES)})")
        return pin

    def home(self, name: str) -> Path:
        """The cached directory of runtime ``name`` at its pinned version."""
        pin = self.pin(name)
        return self._root / "js" / pin.name / pin.version

    def executable(self, name: str) -> Path:
        pin = self.pin(name)
        return self.home(name) / pin.asset(self._host).executable

    def resolve(self, name: str) -> Path:
        """The runtime's executable, downloaded, checked and cached on a miss."""
        pin = self.pin(name)
        asset = pin.asset(self._host)
        executable = self.executable(name)
        if executable.exists():
            return executable
        url = pin.url(asset)
        data = self._fetch(url)
        found = hashlib.sha256(data).hexdigest()
        if found != asset.sha256:
            raise RuntimeUnavailable(
                f"{asset.filename} from {url} has SHA-256 {found}, not the pinned {asset.sha256}"
            )
        home = self.home(name)
        staging = home.parent / f".{home.name}.{os.getpid()}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            try:
                _extract(asset.filename, data, staging)
            except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
                raise RuntimeUnavailable(f"{asset.filename} could not be extracted: {exc}") from exc
            staged = staging / asset.executable
            if not staged.is_file():
                raise RuntimeUnavailable(f"{asset.filename} holds no {asset.executable}")
            # A zip keeps no permission bits: the executable is made executable here.
            staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if executable.exists():  # another process resolved it meanwhile
                return executable
            home.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, home)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return executable
