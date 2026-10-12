# Copyright (c) 2026 Kenneth Stott
# Canary: 4e3afb01-9878-45d1-8248-0d602b17eca6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A Node source's install (REQ-1984): its code fetched from the pinned reference, hashed, its
dependencies installed once with the runtime's frozen-lockfile mode and no install scripts, and
the result cached by content hash.

The source names its code in one of three ways:

- an npm package at an exact version, from the organisation's registry for its scope, else its
  mirror, else the public npm registry; the tarball is checked against the registry's integrity;
- a Git repository at a commit (a tag is resolved to its commit when the source is saved), with
  a subdirectory;
- an archive uploaded to Provisa.

The content hash is taken over the bundle's files BEFORE any install, and is what a source
records: a later install that finds other content is refused, naming both hashes.

Credentials come from the organisation's package registries only (core/package_registries). The
install's configuration (an ``.npmrc`` for every runtime, a Git configuration for Git
dependencies) is written into that install's own directory and removed after it, whether it
succeeded or not; the install runs with a HOME of its own and none of the process's environment
but its PATH, so no other credential reaches it. Nothing installed keeps a credential.
"""

# Requirements: REQ-1984
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 - argv-list invocation only, never shell=True
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from provisa.core.package_registries import GIT, NPM, Resolved
from provisa.node.bundle import BundleRefused, content_hash, unpack

#: The registry an npm package comes from when the organisation names none for it.
NPM_PUBLIC = "https://registry.npmjs.org/"

#: The lockfiles each runtime installs from in its frozen mode.
LOCKFILES: dict[str, tuple[str, ...]] = {
    "node": ("package-lock.json", "npm-shrinkwrap.json"),
    "bun": ("bun.lock", "bun.lockb"),
    "deno": ("deno.lock",),
}

#: Written last into a complete install: the cache's mark that it may be used.
INSTALLED_MARK = ".provisa-installed"

#: The user name a Git host's HTTPS token is sent with.
GIT_TOKEN_USER = "x-access-token"  # nosec B105 - the user name a token is sent with, not a secret

_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class NpmCode:
    package: str
    version: str


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


Code = NpmCode | GitCode | UploadCode


@dataclass(frozen=True)
class Installed:
    #: The installed bundle: its files and, where it has dependencies, its node_modules.
    path: Path
    content_hash: str


#: GET ``url`` with ``headers``; the body. Injected so tests never touch the network.
Http = Callable[[str, dict[str, str]], bytes]
#: Run ``argv`` in ``cwd`` with exactly ``env``; raises :class:`InstallFailed` on a non-zero exit.
Runner = Callable[[Sequence[str], Path, dict[str, str]], None]


class InstallFailed(BundleRefused):
    """The runtime's install exited with an error; its output is the message."""


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
    # The runtime's own install, from the pinned runtime, with a fixed argv and no shell.
    done = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True)  # nosec B603
    if done.returncode != 0:
        output = (done.stdout + done.stderr).strip().splitlines()[-40:]
        raise InstallFailed(
            "install_failed",
            f"{Path(argv[0]).name} {' '.join(argv[1:3])} exited {done.returncode}: "
            + "\n".join(output),
        )


# -- registries ------------------------------------------------------------------------------------


def _slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def npm_registry_for(package: str, registries: Sequence[Resolved]) -> Resolved | None:
    """The organisation's registry ``package`` is installed from: the one for its scope, else the
    mirror; None for the public npm registry."""
    npm = [r for r in registries if r.kind == NPM]
    if package.startswith("@"):
        scope = package.split("/", 1)[0]
        for registry in npm:
            if registry.scope == scope:
                return registry
    for registry in npm:
        if registry.mirror:
            return registry
    return None


def npmrc(registries: Sequence[Resolved]) -> str:
    """The ``.npmrc`` every runtime reads: the mirror as the default registry, each scope's
    registry, and each registry's token for its own address."""
    lines: list[str] = []
    for registry in registries:
        if registry.kind != NPM:
            continue
        address = _slash(registry.address)
        if registry.mirror:
            lines.append(f"registry={address}")
        if registry.scope:
            lines.append(f"{registry.scope}:registry={address}")
        parts = urlsplit(address)
        lines.append(f"//{parts.netloc}{parts.path}:_authToken={registry.credential}")
    return "\n".join(lines) + "\n"


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


def _integrity_ok(data: bytes, integrity: str) -> bool:
    """Whether ``data`` matches any of the Subresource Integrity values npm gives a tarball."""
    for token in integrity.split():
        algorithm, _, expected = token.partition("-")
        if algorithm in ("sha512", "sha384", "sha256"):
            if base64.b64encode(hashlib.new(algorithm, data).digest()).decode() == expected:
                return True
    return False


def fetch_npm(
    code: NpmCode,
    registries: Sequence[Resolved],
    http: Http,
    dest: Path,
    *,
    pinned_integrity: str | None = None,
) -> Path:
    """The package's files at its exact version, checked against the registry's integrity -- and,
    for a package Provisa itself pins, against ``pinned_integrity``, which the registry must
    give too: a mirror cannot substitute another tarball."""
    if not _EXACT_VERSION.match(code.version):
        raise BundleRefused(
            "version_not_exact",
            f"{code.package}@{code.version} is not an exact version",
            package=code.package,
            version=code.version,
        )
    registry = npm_registry_for(code.package, registries)
    base = _slash(registry.address) if registry else NPM_PUBLIC
    headers = {"Accept": "application/json"}
    if registry is not None:
        headers["Authorization"] = f"Bearer {registry.credential}"
    meta = json.loads(http(base + quote(code.package, safe="@"), headers))
    found = (meta.get("versions") or {}).get(code.version)
    if found is None:
        raise BundleRefused(
            "version_not_found",
            f"{code.package}@{code.version} is not in {base}",
            package=code.package,
            version=code.version,
        )
    dist = found.get("dist") or {}
    tarball, integrity = dist.get("tarball"), dist.get("integrity")
    if pinned_integrity is not None and integrity != pinned_integrity:
        raise BundleRefused(
            "integrity_mismatch",
            f"{base} gives {code.package}@{code.version} the integrity {integrity}, not the pinned "
            f"{pinned_integrity}",
            package=code.package,
        )
    if not tarball or not integrity:
        raise BundleRefused(
            "no_integrity",
            f"{base} gives {code.package}@{code.version} no tarball integrity to check",
            package=code.package,
        )
    # The token goes only to the registry's own host.
    same_host = registry is not None and urlsplit(tarball).netloc == urlsplit(base).netloc
    data = http(tarball, {"Authorization": headers["Authorization"]} if same_host else {})
    if not _integrity_ok(data, integrity):
        raise BundleRefused(
            "integrity_mismatch",
            f"{code.package}@{code.version} from {tarball} does not match the registry's integrity",
            package=code.package,
        )
    return unpack(f"{code.package.replace('/', '-')}-{code.version}.tgz", data, dest)


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


def fetch(code: Code, registries: Sequence[Resolved], http: Http, dest: Path) -> Path:
    if isinstance(code, NpmCode):
        return fetch_npm(code, registries, http, dest)
    if isinstance(code, GitCode):
        return fetch_git(code, registries, dest)
    return unpack(code.filename, code.data, dest)


# -- installing its dependencies --------------------------------------------------------------------


def needs_install(root: Path, runtime: str) -> bool:
    """Whether the bundle has dependencies to install. A bundle that declares none (a single
    pre-bundled file) needs no install; one that does must carry a lockfile its runtime reads."""
    manifest = root / "package.json"
    declared: dict = {}
    if manifest.is_file():
        package = json.loads(manifest.read_text())
        for field in ("dependencies", "optionalDependencies"):
            declared.update(package.get(field) or {})
    if not declared:
        return False
    if not any((root / name).is_file() for name in LOCKFILES[runtime]):
        raise BundleRefused(
            "no_lockfile",
            f"the bundle declares dependencies but carries no {' or '.join(LOCKFILES[runtime])} "
            f"for {runtime}",
            runtime=runtime,
        )
    return True


def install_command(runtime: str, executable: Path) -> list[str]:
    """The runtime's frozen-lockfile install, with no install scripts."""
    if runtime == "node":
        return [
            str(executable),
            str(_npm_cli(executable)),
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ]
    if runtime == "bun":
        return [str(executable), "install", "--frozen-lockfile", "--ignore-scripts"]
    if runtime == "deno":
        # Deno runs no lifecycle script without --allow-scripts.
        return [str(executable), "install", "--frozen"]
    raise BundleRefused("unknown_runtime", f"{runtime!r} is not a runtime", runtime=runtime)


def _npm_cli(node: Path) -> Path:
    """npm as Node's own release lays it out beside the executable."""
    for candidate in (
        node.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
        node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js",
    ):
        if candidate.is_file():
            return candidate
    raise BundleRefused("no_npm", f"no npm beside {node}", node=str(node))


def _install(
    root: Path, runtime: str, executable: Path, registries: Sequence[Resolved], run: Runner
) -> None:
    """Install ``root``'s dependencies with configuration written into an isolated directory of
    the install's own, removed when it ends."""
    with tempfile.TemporaryDirectory(prefix="provisa-node-install-") as scratch:
        home = Path(scratch)
        rc, git = home / ".npmrc", home / ".gitconfig"
        rc.write_text(npmrc(registries))
        git.write_text(gitconfig(registries))
        project_rc = root / ".npmrc"
        had_rc = project_rc.exists()
        if not had_rc:
            # Bun and Deno read the project's .npmrc; it is the install's, and goes with it.
            project_rc.write_text(rc.read_text())
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "NPM_CONFIG_USERCONFIG": str(rc),
            "npm_config_cache": str(home / "npm-cache"),
            "BUN_INSTALL_CACHE_DIR": str(home / "bun-cache"),
            "GIT_CONFIG_GLOBAL": str(git),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            # Deno's own cache is kept with the install: the worker reads its npm packages there.
            "DENO_DIR": str(root / ".deno"),
        }
        try:
            run(install_command(runtime, executable), root, env)
        finally:
            if not had_rc:
                project_rc.unlink(missing_ok=True)


def install_root(cache_root: Path) -> Path:
    return cache_root / "node-bundles"


def ensure_installed(
    *,
    source_id: str,
    runtime: str,
    code: Code,
    expected_hash: str | None,
    registries: Sequence[Resolved],
    runtime_executable: Path,
    cache_root: Path,
    http: Http = http_get,
    run: Runner = run_command,
) -> Installed:
    """The source's bundle, installed and cached under ``<cache_root>/node-bundles/<runtime>/
    <content hash>/``. A complete install already cached is used as it is.

    ``expected_hash`` is the hash the source recorded when it was saved; None when it is being
    saved now, and the hash found is then the one to record. Content whose hash is not the
    recorded one is refused by the source's name and both hashes."""
    if runtime not in LOCKFILES:
        raise BundleRefused("unknown_runtime", f"{runtime!r} is not a runtime", runtime=runtime)
    base = install_root(cache_root) / runtime
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=base))
    try:
        root = fetch(code, registries, http, staging / "code")
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
        if needs_install(root, runtime):
            _install(root, runtime, runtime_executable, registries, run)
        (root / INSTALLED_MARK).write_text(found)
        if (target / INSTALLED_MARK).exists():  # another process completed it meanwhile
            return Installed(target, found)
        if target.exists():  # an incomplete install from a process that died: replaced
            shutil.rmtree(target)
        os.replace(root, target)
        return Installed(target, found)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
