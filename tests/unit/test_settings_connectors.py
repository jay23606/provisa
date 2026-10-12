# Copyright (c) 2026 Kenneth Stott
# Canary: 15d714f9-6593-4cb4-8e1e-28146d04ed37
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Each connector's bundle folder is an operator setting (REQ-1954): declared once per connector
with a bundled server, on the Connector servers card, unset by default (the pinned release), and
the one value the bundle resolver reads."""

from __future__ import annotations

import pytest

from provisa.core import settings_registry
from provisa.runtime_deps import pgwire_bundles as rd


def _declared() -> dict[str, settings_registry.Setting]:
    return {s.key: s for s in settings_registry.all_settings()}


def test_every_connector_with_a_bundle_has_its_folder_setting():
    declared = _declared()
    for connector in set(rd.BUNDLE_CONNECTOR.values()):
        s = declared[f"connectors.{connector}.bundle_dir"]
        assert (s.card, s.type, s.nullable, s.default) == ("connectors", "str", True, None)
        assert s.env == f"PROVISA_PGWIRE_BUNDLE_{connector.upper()}"
    assert "connectors" in settings_registry.CARDS


def test_unset_the_pinned_release_is_resolved(tmp_path, monkeypatch):
    monkeypatch.delenv("PROVISA_PGWIRE_BUNDLE_SALESFORCE", raising=False)
    fetched = []

    def download(spec, dest):
        fetched.append(spec.version)
        (dest / "bin").mkdir(parents=True)
        (dest / "bin" / spec.artifact_name).write_text("")

    spec = rd.bundle_spec_for("salesforce")
    resolver = rd.BundleResolver(cache_root=tmp_path, downloader=download)
    assert resolver.resolve(spec) == tmp_path / spec.version / "pgwire-salesforce"
    assert fetched == [spec.version]


def test_the_resolver_reads_the_setting_not_the_environment(tmp_path, monkeypatch):
    bundle = tmp_path / "built"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "bin" / "pgwire-splunk").write_text("")
    monkeypatch.setattr(
        settings_registry,
        "value",
        lambda key: str(bundle) if key == "connectors.splunk.bundle_dir" else None,
    )

    def download(spec, dest):
        raise AssertionError("the pinned release was fetched")

    resolver = rd.BundleResolver(cache_root=tmp_path / "cache", downloader=download)
    assert resolver.resolve(rd.bundle_spec_for("splunk")) == bundle
    with pytest.raises(rd.BundleUnavailable, match="connectors.splunk.bundle_dir"):
        monkeypatch.setattr(
            settings_registry,
            "value",
            lambda key: str(tmp_path / "empty") if key.endswith("bundle_dir") else None,
        )
        resolver.resolve(rd.bundle_spec_for("splunk"))
