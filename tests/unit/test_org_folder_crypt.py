# Copyright (c) 2026 Kenneth Stott
# Canary: 1f6b3d82-4e9a-4c57-a2d0-8b5e7c1f3a64
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""An org's folder, encrypted under a key the org holds (REQ-1992): what can be judged without
FUSE. Mounting with gocryptfs is proved on Linux by tests/integration/test_org_folder_crypt.py."""

from __future__ import annotations

import pytest

from provisa.core import org_folder_crypt as crypt
from provisa.core.org_folder_crypt import FolderSettings


@pytest.mark.parametrize(
    "reference",
    ["s3cr3t-key-value", "${env:FILES_KEY}", "${secret:}", "prefix ${secret:k}"],
)
def test_a_key_is_named_by_one_secret_of_the_orgs_vault_never_entered(reference):
    with pytest.raises(crypt.InvalidKeyReference, match="secrets vault"):
        crypt.check_settings(FolderSettings(True, reference))


def test_encryption_needs_the_reference_of_its_key():
    with pytest.raises(crypt.InvalidKeyReference, match="needs the reference"):
        crypt.check_settings(FolderSettings(True, None))
    crypt.check_settings(FolderSettings(True, "${secret:files_key}"))
    crypt.check_settings(FolderSettings(False, None))


def test_what_changes_the_folders_files(tmp_path):
    folder = tmp_path / "orgs" / "acme"
    folder.mkdir(parents=True)
    plain = FolderSettings(False, None)
    on = FolderSettings(True, "${secret:a}")
    assert crypt.changes(folder, plain) is False
    assert crypt.changes(folder, on) is True
    cipher = tmp_path / "orgs" / ".acme.crypt"
    cipher.mkdir()
    (cipher / "gocryptfs.conf").write_text("{}")
    (tmp_path / "orgs" / ".acme.ref").write_text("${secret:a}")
    assert crypt.changes(folder, on) is False
    assert crypt.changes(folder, FolderSettings(True, "${secret:b}")) is True  # a rotated key
    assert crypt.changes(folder, plain) is True


def test_a_plain_folder_is_made_and_nothing_is_asked_of_the_vault(tmp_path):
    folder = tmp_path / "orgs" / "acme"

    def key_of(_reference: str) -> str:
        raise AssertionError("a plain folder reads no key")

    crypt.apply("acme", folder, FolderSettings(False, None), key_of)
    assert folder.is_dir()


def test_encryption_on_a_node_that_cannot_is_refused_naming_the_org(tmp_path, monkeypatch):
    monkeypatch.setattr(crypt.sys, "platform", "darwin")
    with pytest.raises(crypt.FolderEncryptionUnsupported, match="'acme'.*macOS"):
        crypt.apply(
            "acme", tmp_path / "orgs" / "acme", FolderSettings(True, "${secret:k}"), lambda r: "k"
        )


def test_a_key_the_vault_will_not_give_refuses_the_folder_naming_the_org(tmp_path, monkeypatch):
    monkeypatch.setattr(crypt, "_require_tool", lambda org_id: None)

    def revoked(reference: str) -> str:
        raise crypt.FolderKeyUnavailable("acme", "AccessDenied")

    with pytest.raises(crypt.FolderKeyUnavailable, match="'acme'"):
        crypt.apply(
            "acme", tmp_path / "orgs" / "acme", FolderSettings(True, "${secret:k}"), revoked
        )


def test_the_key_goes_to_gocryptfs_on_its_standard_input_only(monkeypatch):
    seen: dict = {}

    def run(args, **kw):
        seen.update(args=args, **kw)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(crypt.subprocess, "run", run)
    crypt._gocryptfs(["-init", "/x"], "the-key")
    assert seen["input"] == b"the-key"
    assert "the-key" not in " ".join(seen["args"])
    assert "env" not in seen
    assert seen["args"][:4] == ["gocryptfs", "-q", "-passfile", "/dev/stdin"]
