# Copyright (c) 2026 Kenneth Stott
# Canary: 39a3a31b-571b-47de-8868-b2c52d1b0859
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What every code source's install shares (REQ-1984, REQ-1993): its code fetched from a pinned
Git commit or an uploaded archive, hashed BEFORE any install, its dependencies installed by its
language, and the result cached by content hash.

A language adds its own package reference (an npm package, a PyPI wheel) and its own dependency
install; :func:`ensure_installed` takes both as callables. The content hash is what a source
records: a later install that finds other content is refused, naming both hashes.

Credentials come from the organisation's package registries only (core/package_registries). A
Git host's token is given to the fetch for that host and to nothing else.
"""

# Requirements: REQ-1984, REQ-1993
from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - argv-list invocation only, never shell=True
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from provisa.codesource.bundle import BundleRefused, content_hash, unpack
from provisa.core.package_registries import GIT, Resolved

#: Written last into a complete install: the cache's mark that it may be used.
INSTALLED_MARK = ".provisa-installed"

#: The user name a Git host's HTTPS token is sent with.
GIT_TOKEN_USER = "x-access-token"  # nosec B105 - the user name a token is sent with, not a secret

_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class GitCode:
    repository: str
    #: The commit fetched: a tag is resolved to its commit when the source is saved.
    commit: str
    subdirectory: str = ""


@dataclass(frozen=True)
class UploadCode:
    """An archive uploaded to Provisa, read from the organisation's store by the caller."""

    filename: str
    data: bytes


@dataclass(frozen=True)
class Installed:
    #: The installed bundle: its files and, where it has dependencies, what its language installed.
    path: Path
    content_hash: str


#: GET ``url`` with ``headers``; the body. Injected so tests never touch the network.
Http = Callable[[str, dict[str, str]], bytes]
#: Run ``argv`` in ``cwd`` with exactly ``env``; raises :class:`InstallFailed` on a non-zero exit.
Runner = Callable[[Sequence[str], Path, dict[str, str]], None]


class InstallFailed(BundleRefused):
    """The language's install exited with an error; its output is the message."""


def http_get(url: str, headers: dict[str, str]) -> bytes:
    import httpx

    if not url.startswith("https://"):
        raise BundleRefused("not_https", f"refusing a non-https address: {url}", url=url)
    try:
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=300.0)
    except httpx.HTTPError as exc:
        raise BundleRefused("fetch_failed", f"could not fetch {url}: {exc}", url=url) from exc
    if response.status_code != 200:
        raise BundleRefused(
            "fetch_failed", f"could not fetch {url}: HTTP {response.status_code}", url=url
        )
    return response.content


def run_command(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> None:
    # The language's own install, from the pinned runtime, with a fixed argv and no shell.
    done = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True)  # nosec B603
    if done.returncode != 0:
        output = (done.stdout + done.stderr).strip().splitlines()[-40:]
        raise InstallFailed(
            "install_failed",
            f"{Path(argv[0]).name} {' '.join(argv[1:3])} exited {done.returncode}: "
            + "\n".join(output),
        )


# -- Git hosts --------------------------------------------------------------------------------------


def gitconfig(registries: Sequence[Resolved]) -> str:
    """The Git configuration a dependency fetched by Git reads: each Git host's address rewritten
    to carry its token."""
    lines: list[str] = []
    for registry in registries:
        if registry.kind != GIT:
            continue
        host = registry.address.strip().rstrip("/")
        token = quote(registry.credential, safe="")
        lines += [
            f'[url "https://{GIT_TOKEN_USER}:{token}@{host}/"]',
            f"\tinsteadOf = https://{host}/",
        ]
    return "\n".join(lines) + "\n"


def git_host_for(url: str, registries: Sequence[Resolved]) -> Resolved | None:
    host = urlsplit(url).netloc.rsplit("@", 1)[-1]
    for registry in registries:
        if registry.kind == GIT and registry.address.strip().rstrip("/") == host:
            return registry
    return None


# -- fetching the code ------------------------------------------------------------------------------


def fetch_git(code: GitCode, registries: Sequence[Resolved], dest: Path) -> Path:
    """The repository's tree at the commit, and the bundle's subdirectory of it."""
    from dulwich import porcelain

    if not _COMMIT.match(code.commit):
        raise BundleRefused(
            "commit_not_pinned",
            f"{code.commit!r} is not a commit; a tag is resolved to its commit when the source is saved",
            commit=code.commit,
        )
    if not code.repository.startswith("https://"):
        raise BundleRefused(
            "not_https", f"refusing a non-https repository: {code.repository}", url=code.repository
        )
    host = git_host_for(code.repository, registries)
    try:
        with open(os.devnull, "wb") as quiet:
            repo = (
                porcelain.clone(code.repository, str(dest), checkout=False, errstream=quiet)
                if host is None
                else porcelain.clone(
                    code.repository,
                    str(dest),
                    checkout=False,
                    errstream=quiet,
                    username=GIT_TOKEN_USER,
                    password=host.credential,
                )
            )
            porcelain.reset(repo, "hard", code.commit)
    except Exception as exc:  # noqa: BLE001 -- dulwich raises many kinds; each is a fetch that failed, named
        raise BundleRefused(
            "fetch_failed",
            f"could not fetch {code.repository} at {code.commit}: {type(exc).__name__}: {exc}",
            url=code.repository,
        ) from exc
    shutil.rmtree(dest / ".git", ignore_errors=True)
    root = (dest / code.subdirectory).resolve() if code.subdirectory else dest.resolve()
    if not root.is_relative_to(dest.resolve()) or not root.is_dir():
        raise BundleRefused(
            "no_subdirectory",
            f"{code.repository} at {code.commit} has no directory {code.subdirectory!r}",
            subdirectory=code.subdirectory,
        )
    return root


def fetch_kept(code: GitCode | UploadCode, registries: Sequence[Resolved], dest: Path) -> Path:
    """The code of a Git or uploaded reference, the two every language shares."""
    if isinstance(code, GitCode):
        return fetch_git(code, registries, dest)
    return unpack(code.filename, code.data, dest)


# -- the cache --------------------------------------------------------------------------------------


def install_root(cache_root: Path) -> Path:
    return cache_root / "code-bundles"


def ensure_installed(
    *,
    source_id: str,
    runtime: str,
    fetch: Callable[[Path], Path],
    install: Callable[[Path], None],
    expected_hash: str | None,
    cache_root: Path,
) -> Installed:
    """The source's bundle, installed and cached under ``<cache_root>/code-bundles/<runtime>/
    <content hash>/``. A complete install already cached is used as it is.

    ``fetch(dest)`` puts the code under ``dest`` and returns the bundle's root; ``install(root)``
    installs its dependencies in place, or does nothing when it has none. ``expected_hash`` is the
    hash the source recorded when it was saved; None when it is being saved now, and the hash
    found is then the one to record. Content whose hash is not the recorded one is refused by the
    source's name and both hashes."""
    base = install_root(cache_root) / runtime
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=base))
    try:
        root = fetch(staging / "code")
        found = content_hash(root)
        if expected_hash is not None and found != expected_hash:
            raise BundleRefused(
                "content_changed",
                f"source {source_id!r}: the code fetched has hash {found}, not the {expected_hash} "
                "recorded when the source was saved",
                source=source_id,
                expected=expected_hash,
                found=found,
            )
        target = base / found
        if (target / INSTALLED_MARK).exists():
            return Installed(target, found)
        install(root)
        (root / INSTALLED_MARK).write_text(found)
        if (target / INSTALLED_MARK).exists():  # another process completed it meanwhile
            return Installed(target, found)
        if target.exists():  # an incomplete install from a process that died: replaced
            shutil.rmtree(target)
        os.replace(root, target)
        return Installed(target, found)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
