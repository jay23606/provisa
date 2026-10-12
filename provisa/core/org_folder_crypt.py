# Copyright (c) 2026 Kenneth Stott
# Canary: 4d8b2e60-7a1c-4f93-b5e2-0c9a3f6d8e15
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An org's folder, encrypted under a key the org holds (REQ-1992).

An org that turns encryption on names its key by a reference into its own secrets vault
(``${secret:NAME}``: AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, HashiCorp Vault, as
the org's vault is configured). Provisa stores the reference and never the key. On each node the
folder's files are kept encrypted by gocryptfs in ``<data dir>/orgs/.<org>.crypt`` and mounted, as
plain paths, at the org's folder: the key is resolved from the vault when the folder is mounted and
passed to gocryptfs on a pipe -- never in a file, an argument or the environment -- and exists only
in the mount's memory from then on. The files are durable: nothing is deleted when a mount ends.

- Turning encryption on encrypts what the folder holds; turning it off decrypts it. Nothing is lost
  either way.
- A changed reference (a rotated key) re-encrypts the folder under the new key, read with the one
  the folder was encrypted under.
- A reference the vault will not resolve (access revoked) refuses the folder, naming the org.
- A key that does not open the folder (lost, replaced in the vault) refuses the folder, naming the
  org; nothing is reset. The files are discarded only when an org admin deliberately sets a new
  key and the folder's own key can no longer be read: that reset is logged naming the org.

A deployment of several nodes shares one mount of the data folder (``org_files.shared_mount``):
every node mounts the same ciphertext, with ``-sharedstorage``, and records that it does under
``orgs/.<org>.mounted/<node id>``. A change of the folder's encryption (on, off, a new key) moves
its files, so it applies only while no other node holds a mount, and is refused naming them
otherwise; they mount the folder again at their next runtime build.

gocryptfs needs FUSE: a Linux host or container with /dev/fuse. On macOS the setting is refused by
name.
"""

# Requirements: REQ-1992
from __future__ import annotations

import fcntl
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

#: A key reference is one secret of the org's vault, by name.
_REFERENCE = re.compile(r"\$\{secret:[^}]+\}")
#: gocryptfs's exit code for a password that does not open the folder.
_WRONG_PASSWORD = 12
_CONF = "gocryptfs.conf"


class FolderKeyUnavailable(RuntimeError):
    """The org's key reference did not resolve: the folder cannot be opened."""

    def __init__(self, org_id: str, why: str) -> None:
        super().__init__(
            f"org {org_id!r}'s file folder cannot be opened: its encryption key could not be read "
            f"from the org's vault ({why})"
        )
        self.org_id = org_id


class FolderEncryptionUnsupported(RuntimeError):
    """This node cannot encrypt a folder."""

    def __init__(self, org_id: str, why: str) -> None:
        super().__init__(f"org {org_id!r}'s file folder cannot be encrypted on this node: {why}")
        self.org_id = org_id


class FolderInUse(RuntimeError):
    """A change of the folder's encryption while other nodes hold a mount of it."""

    def __init__(self, org_id: str, nodes: list[str], markers: Path) -> None:
        super().__init__(
            f"org {org_id!r}'s file folder is mounted on other nodes ({', '.join(nodes)}); a "
            "change to its encryption applies once they have released it. A node that no longer "
            f"runs still holds its mount until its entry under {markers} is removed"
        )
        self.org_id = org_id
        self.nodes = nodes


class InvalidKeyReference(ValueError):
    """A key reference that is not one secret of the org's vault."""


@dataclass(frozen=True)
class FolderSettings:
    """Whether the org's folder is encrypted, and the reference that names its key."""

    encrypted: bool
    key_reference: str | None


def check_settings(settings: FolderSettings) -> None:
    """Refuse settings that cannot be applied: encryption needs a reference, and a reference is
    ``${secret:NAME}`` -- never a key."""
    if settings.key_reference is not None and not _REFERENCE.fullmatch(settings.key_reference):
        raise InvalidKeyReference(
            "the key is named by a reference into the organization's secrets vault, written "
            "${secret:NAME}; the key itself is never entered here"
        )
    if settings.encrypted and settings.key_reference is None:
        raise InvalidKeyReference("encrypting the folder needs the reference of its key")


Resolve = Callable[[str], Awaitable[str]]


def _markers(folder: Path) -> Path:
    """Where each node that holds a mount of the folder records it, by its node id."""
    return folder.parent / f".{folder.name}.mounted"


def _mounted_elsewhere(folder: Path) -> list[str]:
    """The other nodes that hold a mount of the folder."""
    from provisa.core.org_files import node_id

    markers = _markers(folder)
    if not markers.is_dir():
        return []
    return sorted(m.name for m in markers.iterdir() if m.name != node_id())


def _paths(folder: Path) -> tuple[Path, Path, Path, Path]:
    """(the ciphertext, the reference it is encrypted under, a staging directory, the lock)."""
    base = folder.parent
    return (
        base / f".{folder.name}.crypt",
        base / f".{folder.name}.ref",
        base / f".{folder.name}.staging",
        base / f".{folder.name}.lock",
    )


@contextmanager
def _locked(lock: Path) -> Iterator[None]:
    """One change of the folder at a time on this node, across its processes."""
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _gocryptfs(args: list[str], key: str) -> int:
    """Run gocryptfs with the key on its standard input: a pipe, never a file, an argument or
    the environment."""
    done = subprocess.run(  # noqa: S603 - code-built arguments
        ["gocryptfs", "-q", "-passfile", "/dev/stdin", *args],
        input=key.encode(),
        capture_output=True,
        check=False,
    )
    return done.returncode


def _require_tool(org_id: str) -> None:
    if sys.platform == "darwin":
        raise FolderEncryptionUnsupported(
            org_id, "folder encryption needs gocryptfs and FUSE, which macOS does not run"
        )
    if shutil.which("gocryptfs") is None or not os.path.exists("/dev/fuse"):
        raise FolderEncryptionUnsupported(
            org_id, "gocryptfs and /dev/fuse are not available on this node"
        )


def _init(org_id: str, cipher: Path, key: str) -> None:
    cipher.mkdir(mode=0o700, parents=True, exist_ok=True)
    code = _gocryptfs(["-init", str(cipher)], key)
    if code != 0:
        raise FolderEncryptionUnsupported(org_id, f"gocryptfs -init exited with {code}")


def _mount(cipher: Path, folder: Path, key: str) -> int:
    """Mount the ciphertext at the folder, recording that this node holds a mount. On a mount
    shared across nodes, with ``-sharedstorage``: every node mounts the same ciphertext."""
    from provisa.core.org_files import node_id, shared_mount

    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    shared = ["-sharedstorage"] if shared_mount() else []
    code = _gocryptfs([*shared, str(cipher), str(folder)], key)
    if code == 0:
        markers = _markers(folder)
        markers.mkdir(mode=0o700, parents=True, exist_ok=True)
        (markers / node_id()).touch()
    return code


def _unmount(folder: Path) -> None:
    from provisa.core.org_files import node_id

    tool = shutil.which("fusermount3") or shutil.which("fusermount") or "umount"
    args = [tool, "-u", str(folder)] if "fusermount" in tool else [tool, str(folder)]
    subprocess.run(args, check=True, capture_output=True)  # noqa: S603
    (_markers(folder) / node_id()).unlink(missing_ok=True)


def _move_contents(source: Path, target: Path) -> None:
    """Every entry of ``source`` into ``target``: copied, then removed from ``source``."""
    for entry in list(source.iterdir()):
        destination = target / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, destination, symlinks=True, dirs_exist_ok=True)
            shutil.rmtree(entry)
        else:
            shutil.copy2(entry, destination, follow_symlinks=False)
            entry.unlink()


def _reset(org_id: str, folder: Path, cipher: Path, ref_file: Path, why: str) -> None:
    """The one place an org's files are discarded: an org admin set a new key and the folder's
    own key can no longer be read."""
    log.warning(
        "org %s: a new key was set for its file folder and the key it was encrypted under can no "
        "longer be read (%s); its files are reset and rebuilt as needed",
        org_id,
        why,
    )
    if os.path.ismount(folder):
        _unmount(folder)
    shutil.rmtree(cipher, ignore_errors=True)
    ref_file.unlink(missing_ok=True)


def changes(folder: Path, settings: FolderSettings) -> bool:
    """Whether applying ``settings`` would move the folder's files: encryption turned on or off,
    or its key changed. Whatever holds files open in the folder is stopped first."""
    cipher, ref_file, _staging, _lock = _paths(folder)
    encrypted_now = (cipher / _CONF).exists()
    if settings.encrypted != encrypted_now:
        return True
    recorded = ref_file.read_text().strip() if ref_file.exists() else None
    return settings.encrypted and recorded != settings.key_reference


def apply(
    org_id: str, folder: Path, settings: FolderSettings, key_of: Callable[[str], str]
) -> None:
    """Make ``folder`` what ``settings`` say on this node. ``key_of`` reads a reference's key from
    the org's vault, raising :class:`FolderKeyUnavailable` when it cannot."""
    cipher, ref_file, staging, lock = _paths(folder)
    with _locked(lock):
        encrypted_now = (cipher / _CONF).exists()
        if changes(folder, settings):
            others = _mounted_elsewhere(folder)
            if others:
                raise FolderInUse(org_id, others, _markers(folder))
        if not settings.encrypted:
            if encrypted_now:
                _decrypt_out(org_id, folder, cipher, ref_file, staging, key_of)
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            return
        _require_tool(org_id)
        assert settings.key_reference is not None  # check_settings: encryption names its key
        key = key_of(settings.key_reference)
        if encrypted_now:
            recorded = ref_file.read_text().strip() if ref_file.exists() else None
            if recorded != settings.key_reference:
                _reencrypt(org_id, folder, cipher, ref_file, staging, key_of, recorded, key)
        else:
            _encrypt_in(org_id, folder, cipher, staging, key)
        ref_file.write_text(settings.key_reference)
        if os.path.ismount(folder):
            return
        code = _mount(cipher, folder, key)
        if code == _WRONG_PASSWORD:
            raise FolderKeyUnavailable(
                org_id, "the key the vault holds is not the one the folder is encrypted under"
            )
        if code != 0:
            raise FolderEncryptionUnsupported(org_id, f"gocryptfs exited with {code} mounting it")


def _encrypt_in(org_id: str, folder: Path, cipher: Path, staging: Path, key: str) -> None:
    """Off -> on: what the plain folder holds is encrypted into the mount."""
    _init(org_id, cipher, key)
    if not folder.is_dir() or not any(folder.iterdir()):
        return
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    _move_contents(folder, staging)
    code = _mount(cipher, folder, key)
    if code != 0:
        _move_contents(staging, folder)
        raise FolderEncryptionUnsupported(org_id, f"gocryptfs exited with {code} mounting it")
    _move_contents(staging, folder)
    staging.rmdir()


def _decrypt_out(
    org_id: str,
    folder: Path,
    cipher: Path,
    ref_file: Path,
    staging: Path,
    key_of: Callable[[str], str],
) -> None:
    """On -> off: what the encrypted folder holds is decrypted into a plain folder."""
    recorded = ref_file.read_text().strip() if ref_file.exists() else None
    if not os.path.ismount(folder):
        if recorded is None:
            raise FolderKeyUnavailable(
                org_id, "there is no record of the key it is encrypted under"
            )
        _require_tool(org_id)
        code = _mount(cipher, folder, key_of(recorded))
        if code == _WRONG_PASSWORD:
            raise FolderKeyUnavailable(
                org_id, "the key the vault holds is not the one the folder is encrypted under"
            )
        if code != 0:
            raise FolderEncryptionUnsupported(org_id, f"gocryptfs exited with {code} mounting it")
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    _move_contents(folder, staging)
    _unmount(folder)
    shutil.rmtree(cipher)
    ref_file.unlink(missing_ok=True)
    folder.rmdir()
    staging.rename(folder)


def _reencrypt(
    org_id: str,
    folder: Path,
    cipher: Path,
    ref_file: Path,
    staging: Path,
    key_of: Callable[[str], str],
    recorded: str | None,
    key: str,
) -> None:
    """A new key set by an org admin: the folder is read with the key it was encrypted under and
    encrypted anew. Where that key can no longer be read, the folder is reset under the new one --
    the admin's deliberate act, the one reset there is."""
    try:
        if recorded is None:
            raise FolderKeyUnavailable(org_id, "no record of the key it was encrypted under")
        old = key_of(recorded)
    except FolderKeyUnavailable as gone:
        _reset(org_id, folder, cipher, ref_file, str(gone))
        _init(org_id, cipher, key)
        return
    if not os.path.ismount(folder):
        code = _mount(cipher, folder, old)
        if code != 0:
            _reset(org_id, folder, cipher, ref_file, f"gocryptfs exited with {code}")
            _init(org_id, cipher, key)
            return
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    _move_contents(folder, staging)
    _unmount(folder)
    shutil.rmtree(cipher)
    _init(org_id, cipher, key)
    code = _mount(cipher, folder, key)
    if code != 0:
        raise FolderEncryptionUnsupported(org_id, f"gocryptfs exited with {code} mounting it")
    _move_contents(staging, folder)
    staging.rmdir()


# -- the org's setting -------------------------------------------------------------------------


async def read_settings(admin_db: Any, org_id: str) -> FolderSettings:
    from sqlalchemy import select

    from provisa.core.schema_admin import orgs

    async with admin_db.acquire() as conn:
        row = (
            await conn.execute_core(
                select(orgs.c.files_encrypted, orgs.c.files_key_reference).where(
                    orgs.c.id == org_id
                )
            )
        ).fetchone()
    if row is None:
        raise LookupError(f"organization {org_id!r} does not exist")
    return FolderSettings(bool(row[0]), row[1])


async def write_settings(admin_db: Any, org_id: str, settings: FolderSettings) -> None:
    from sqlalchemy import update

    from provisa.core.schema_admin import orgs

    check_settings(settings)
    async with admin_db.acquire() as conn:
        await conn.execute_core(
            update(orgs)
            .where(orgs.c.id == org_id)
            .values(files_encrypted=settings.encrypted, files_key_reference=settings.key_reference)
        )


def vault_key_reader(admin_db: Any, org_id: str, loop: Any) -> Callable[[str], str]:
    """Reads a reference's key from the org's own vault, bound for the read, from the thread the
    folder is changed on. A refusal is :class:`FolderKeyUnavailable`."""
    import asyncio

    async def read(reference: str) -> str:
        from provisa.core import secrets_store
        from provisa.core.secrets import resolve_secrets

        async with secrets_store.bound(admin_db, org_id):
            return resolve_secrets(reference)

    def key_of(reference: str) -> str:
        try:
            value = asyncio.run_coroutine_threadsafe(read(reference), loop).result()
        except Exception as refused:  # allow-ble: any failure to read the key is the one refusal of the folder, named by org; the vault's reason is carried in it
            raise FolderKeyUnavailable(org_id, f"{type(refused).__name__}: {refused}") from None
        if not value:
            raise FolderKeyUnavailable(org_id, "the secret is empty")
        return value

    return key_of
