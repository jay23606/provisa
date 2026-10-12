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


# -- one mount shared by every node (org_files.shared_mount) ----------------------------------


class _Gocryptfs:
    """gocryptfs and the mount table as the folder's lifecycle calls them: -init writes the
    folder's config; a mount is recorded; the wrong key exits 12."""

    def __init__(self, monkeypatch, *, key: str = "k1") -> None:
        self.key = key
        self.calls: list[list[str]] = []
        self.mounted: set[str] = set()
        monkeypatch.setattr(crypt, "_gocryptfs", self.run)
        monkeypatch.setattr(crypt.os.path, "ismount", lambda p: str(p) in self.mounted)
        monkeypatch.setattr(crypt.subprocess, "run", self.unmount)
        monkeypatch.setattr(crypt, "_require_tool", lambda org_id: None)

    def run(self, args: list[str], key: str) -> int:
        self.calls.append(args)
        if args[0] == "-init":
            from pathlib import Path

            (Path(args[1]) / "gocryptfs.conf").write_text(key)
            return 0
        from pathlib import Path

        cipher = Path(args[-2])
        if (cipher / "gocryptfs.conf").read_text() != key:
            return 12
        self.mounted.add(args[-1])
        return 0

    def unmount(self, args, **_kw):
        self.mounted.discard(args[-1])
        return type("Done", (), {"returncode": 0})()


@pytest.fixture
def node(monkeypatch):
    """This node's name and whether the mount is shared, as the settings give them."""
    from provisa.core import org_files

    names = {"node": "pod-a", "shared": True}
    monkeypatch.setattr(org_files, "node_id", lambda: names["node"])
    monkeypatch.setattr(org_files, "shared_mount", lambda: names["shared"])
    return names


_ON = FolderSettings(True, "${secret:k}")


def test_each_node_mounts_the_shared_ciphertext_with_sharedstorage_and_records_it(
    tmp_path, monkeypatch, node
):
    fake = _Gocryptfs(monkeypatch)
    folder = tmp_path / "orgs" / "acme"
    crypt.apply("acme", folder, _ON, lambda r: "k1")
    assert fake.calls[-1][0] == "-sharedstorage"
    assert (tmp_path / "orgs" / ".acme.mounted" / "pod-a").exists()


def test_a_mount_a_node_keeps_to_itself_takes_no_sharedstorage(tmp_path, monkeypatch, node):
    node["shared"] = False
    fake = _Gocryptfs(monkeypatch)
    crypt.apply("acme", tmp_path / "orgs" / "acme", _ON, lambda r: "k1")
    assert "-sharedstorage" not in fake.calls[-1]


def test_a_change_while_another_node_holds_a_mount_is_refused_naming_it(
    tmp_path, monkeypatch, node
):
    _Gocryptfs(monkeypatch)
    folder = tmp_path / "orgs" / "acme"
    crypt.apply("acme", folder, _ON, lambda r: "k1")
    (tmp_path / "orgs" / ".acme.mounted" / "pod-b").touch()
    with pytest.raises(crypt.FolderInUse, match="'acme'.*pod-b"):
        crypt.apply("acme", folder, FolderSettings(False, None), lambda r: "k1")
    # Nothing moved: the folder is still encrypted under its key.
    assert (tmp_path / "orgs" / ".acme.crypt" / "gocryptfs.conf").exists()


def test_with_no_other_node_mounted_the_change_applies(tmp_path, monkeypatch, node):
    fake = _Gocryptfs(monkeypatch)
    folder = tmp_path / "orgs" / "acme"
    crypt.apply("acme", folder, _ON, lambda r: "k1")
    (folder / "cache.parquet").write_text("rows")
    fake.mounted.discard(str(folder))  # the fake mount holds no files of its own
    crypt.apply("acme", folder, FolderSettings(False, None), lambda r: "k1")
    assert not (tmp_path / "orgs" / ".acme.crypt").exists()
    assert not (tmp_path / "orgs" / ".acme.mounted" / "pod-a").exists()


def test_a_key_that_does_not_open_the_folder_refuses_it_and_resets_nothing(
    tmp_path, monkeypatch, node
):
    fake = _Gocryptfs(monkeypatch)
    folder = tmp_path / "orgs" / "acme"
    crypt.apply("acme", folder, _ON, lambda r: "k1")
    fake.mounted.clear()  # the node restarted: its mount is gone
    with pytest.raises(crypt.FolderKeyUnavailable, match="'acme'.*not the one the folder"):
        crypt.apply("acme", folder, _ON, lambda r: "a-replaced-key")
    assert (tmp_path / "orgs" / ".acme.crypt" / "gocryptfs.conf").read_text() == "k1"


def test_a_new_key_set_while_the_old_one_is_gone_resets_the_folder_under_it(
    tmp_path, monkeypatch, node
):
    """The one reset there is: an org admin's deliberate new key."""
    _Gocryptfs(monkeypatch)
    folder = tmp_path / "orgs" / "acme"
    crypt.apply("acme", folder, _ON, lambda r: "k1")

    def key_of(reference: str) -> str:
        if reference == "${secret:k}":
            raise crypt.FolderKeyUnavailable("acme", "AccessDenied")
        return "k2"

    crypt.apply("acme", folder, FolderSettings(True, "${secret:k2}"), key_of)
    assert (tmp_path / "orgs" / ".acme.crypt" / "gocryptfs.conf").read_text() == "k2"
    assert (tmp_path / "orgs" / ".acme.ref").read_text() == "${secret:k2}"
