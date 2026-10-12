# Copyright (c) 2026 Kenneth Stott
# Canary: 9c5e2a71-6d3b-4f18-8a04-e7b1c9d2f536
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An org's folder, encrypted with gocryptfs under a key the org holds (REQ-1992), on a real
Linux FUSE mount: what a node does.

Turning encryption on encrypts what the folder holds and nothing is lost; only ciphertext reaches
the storage; a rotated key re-encrypts the folder; turning it off decrypts it; a key that no longer
opens the folder resets it, and nothing else does. Needs gocryptfs and /dev/fuse (the suite lanes
install them, scripts/ci/lanes/suite-prepare.sh); without them the test fails by name.
"""

# Requirements: REQ-1992
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from provisa.core import org_folder_crypt as crypt
from provisa.core.org_folder_crypt import FolderSettings

pytestmark = [pytest.mark.integration]

KEYS = {"${secret:k1}": "first-key-value", "${secret:k2}": "second-key-value"}


@pytest.fixture
def orgs(tmp_path):
    missing = [t for t in ("gocryptfs", "fusermount3") if shutil.which(t) is None]
    assert not missing and os.path.exists("/dev/fuse"), (
        f"this test needs gocryptfs, fusermount3 and /dev/fuse; missing: {missing or '/dev/fuse'}"
    )
    yield tmp_path
    for folder in tmp_path.iterdir():
        if os.path.ismount(folder):
            subprocess.run(["fusermount3", "-u", str(folder)], check=False)


def _key_of(reference: str) -> str:
    if reference not in KEYS:
        raise crypt.FolderKeyUnavailable("acme", "no such secret")
    return KEYS[reference]


def _cipher_holds_no_plaintext(orgs, text: bytes) -> None:
    for root, _dirs, files in os.walk(orgs / ".acme.crypt"):
        for name in files:
            assert text not in (open(os.path.join(root, name), "rb").read())


def test_a_folder_is_encrypted_rotated_and_decrypted_keeping_its_files(orgs):
    folder = orgs / "acme"
    folder.mkdir()
    (folder / "cache").mkdir()
    (folder / "cache" / "orders.parquet").write_bytes(b"plain-bytes-of-orders")

    # Off -> on: the folder's files are encrypted, and read as before through the mount.
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), _key_of)
    assert os.path.ismount(folder)
    assert (folder / "cache" / "orders.parquet").read_bytes() == b"plain-bytes-of-orders"
    _cipher_holds_no_plaintext(orgs, b"plain-bytes-of-orders")
    assert "first-key-value" not in (orgs / ".acme.ref").read_text()

    # Applied again, nothing moves.
    assert crypt.changes(folder, FolderSettings(True, "${secret:k1}")) is False
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), _key_of)

    # A rotated key: the folder is read with the old key and encrypted under the new one.
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k2}"), _key_of)
    assert (folder / "cache" / "orders.parquet").read_bytes() == b"plain-bytes-of-orders"
    subprocess.run(["fusermount3", "-u", str(folder)], check=True)
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k2}"), _key_of)  # remounts
    assert (folder / "cache" / "orders.parquet").read_bytes() == b"plain-bytes-of-orders"

    # On -> off: decrypted into a plain folder, nothing lost, no ciphertext left.
    crypt.apply("acme", folder, FolderSettings(False, None), _key_of)
    assert not os.path.ismount(folder)
    assert (folder / "cache" / "orders.parquet").read_bytes() == b"plain-bytes-of-orders"
    assert not (orgs / ".acme.crypt").exists()


def test_a_key_that_no_longer_opens_the_folder_resets_it(orgs, caplog):
    folder = orgs / "acme"
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), _key_of)
    (folder / "f").write_text("kept until the key is lost")
    subprocess.run(["fusermount3", "-u", str(folder)], check=True)

    # The vault now holds another value under the same name: the old files cannot be read.
    replaced = {"${secret:k1}": "a-different-value"}
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), replaced.__getitem__)
    assert os.path.ismount(folder)
    assert not (folder / "f").exists()
    assert "org acme: its file folder's key no longer opens it" in caplog.text


def test_a_revoked_key_refuses_the_folder_and_keeps_its_files(orgs):
    folder = orgs / "acme"
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), _key_of)
    (folder / "f").write_text("kept")
    subprocess.run(["fusermount3", "-u", str(folder)], check=True)

    def revoked(reference: str) -> str:
        raise crypt.FolderKeyUnavailable("acme", "AccessDenied")

    with pytest.raises(crypt.FolderKeyUnavailable, match="'acme'"):
        crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), revoked)
    crypt.apply("acme", folder, FolderSettings(True, "${secret:k1}"), _key_of)
    assert (folder / "f").read_text() == "kept"
