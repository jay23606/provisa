# Copyright (c) 2026 Kenneth Stott
# Canary: 16d0ccdf-a13c-4947-869d-05de559f2e05
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The test stack's images come from this repository's registry in CI, pinned by digest."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests import ci_images

REPO = Path(__file__).resolve().parents[2]
# The compose files a container-backed test stack is made of (tests/itest_stack.py and
# tests/e2e/conftest.py between them).
STACK_FILES = [
    "docker-compose.core.yml",
    "docker-compose.test.yml",
    "docker-compose.itest.yml",
    "docker-compose.observability.yml",
    "docker-compose.e2e.yml",
]
_DIGEST = re.compile(r"^[a-z0-9.-]+(?:/[a-z0-9._-]+)+@sha256:[0-9a-f]{64}$")


def test_every_listed_image_is_pinned_by_digest_under_its_own_name():
    found = ci_images.entries()
    assert len(found) >= 40
    assert len({entry.name for entry in found.values()}) == len(found)
    for asked, entry in found.items():
        assert _DIGEST.match(entry.upstream), entry.upstream
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry.name), entry.name
        assert "@" not in asked and " " not in asked
        # The copy is addressed by the upstream digest: the same image, not a tag that can move.
        assert entry.mirror == f"ghcr.io/kenstott/provisa/ci-{entry.name}@{entry.digest}"


def test_every_image_the_stack_pulls_is_listed():
    """A pulled image that is not listed would be refused by name in CI; this finds it first."""
    pulled = ci_images.pulled_services([str(REPO / name) for name in STACK_FILES])
    assert len(pulled) >= 40
    missing = sorted(set(pulled.values()) - set(ci_images.entries()))
    assert not missing, missing


def test_nothing_is_listed_that_no_stack_and_no_test_asks_for():
    pulled = set(ci_images.pulled_services([str(REPO / name) for name in STACK_FILES]).values())
    assert set(ci_images.entries()) <= pulled


def test_an_image_the_stack_builds_is_not_overridden():
    pulled = ci_images.pulled_services([str(REPO / name) for name in STACK_FILES])
    core = yaml.safe_load((REPO / "docker-compose.core.yml").read_text())["services"]
    assert "build" in core["zaychik"] and "zaychik" not in pulled


def test_outside_ci_every_reference_is_used_as_written(monkeypatch, tmp_path):
    monkeypatch.delenv(ci_images.ENV, raising=False)
    assert ci_images.image("postgres:16") == "postgres:16"
    out = tmp_path / "override.yml"
    assert ci_images.compose_args([str(REPO / "docker-compose.core.yml")], str(out)) == []
    assert not out.exists()


def test_in_ci_a_test_and_a_stack_get_the_copies(monkeypatch, tmp_path):
    monkeypatch.setenv(ci_images.ENV, "mirror")
    copy = ci_images.image("postgres:16")
    assert copy.startswith("ghcr.io/kenstott/provisa/ci-postgres-16@sha256:")
    out = tmp_path / "stack" / "override.yml"
    files = [str(REPO / name) for name in STACK_FILES[:3]]
    assert ci_images.compose_args(files, str(out)) == ["-f", str(out)]
    override = yaml.safe_load(out.read_text())["services"]
    pulled = ci_images.pulled_services(files)
    assert set(override) == set(pulled)
    assert override["postgres"] == {"image": copy}
    for body in override.values():
        assert set(body) == {"image"} and body["image"].startswith(ci_images.MIRROR)
    assert "zaychik" not in override


def test_in_ci_an_unlisted_image_is_refused_by_name(monkeypatch, tmp_path):
    monkeypatch.setenv(ci_images.ENV, "mirror")
    with pytest.raises(ci_images.NotMirrored, match="nosuch/image:1"):
        ci_images.image("nosuch/image:1")
    compose = tmp_path / "c.yml"
    compose.write_text("services:\n  x:\n    image: nosuch/image:1\n")
    with pytest.raises(ci_images.NotMirrored, match="nosuch/image:1"):
        ci_images.compose_override([str(compose)], str(tmp_path / "o.yml"))


def test_any_other_value_of_the_switch_is_refused(monkeypatch):
    monkeypatch.setenv(ci_images.ENV, "true")
    with pytest.raises(ValueError, match="mirror"):
        ci_images.image("postgres:16")


def test_no_container_backed_test_names_a_listed_image_without_the_helper():
    """A test that starts a container itself asks for its image through ci_images.image(), so
    the same test pulls the copy in CI."""
    listed = set(ci_images.entries())
    offenders = []
    for root in ("tests/integration", "tests/steps", "tests/e2e"):
        for path in (REPO / root).rglob("*.py"):
            text = path.read_text()
            for line_number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for quoted in re.findall(r'"([^"\s]+)"', line):
                    if quoted in listed and f'image("{quoted}")' not in line:
                        offenders.append(f"{path.relative_to(REPO)}:{line_number}: {quoted}")
    assert not offenders, offenders


def _mirror_workflow() -> dict:
    return yaml.safe_load((REPO / ".github/workflows/mirror-ci-images.yml").read_text())


def test_the_mirror_copies_by_digest_and_reads_each_copy_back():
    steps = _mirror_workflow()["jobs"]["mirror"]["steps"]
    copy = next(step["run"] for step in steps if "skopeo copy" in step.get("run", ""))
    assert "skopeo copy --all --preserve-digests" in copy
    # Read back by the upstream digest after the copy: a different image is a failed step.
    assert copy.index("skopeo copy") < copy.rindex(
        'skopeo inspect --raw "docker://${target}@${digest}"'
    )
    assert "set -euo pipefail" in copy
    # ... and readable by a lane, which has no credentials: checked after logging out.
    check = next(step["run"] for step in steps if "skopeo logout" in step.get("run", ""))
    assert check.index("skopeo logout") < check.index("skopeo inspect")
    assert "exit 1" in check


def test_only_the_mirror_job_may_write_packages_and_it_reads_no_repository_secret():
    text = (REPO / ".github/workflows/mirror-ci-images.yml").read_text()
    workflow = _mirror_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["mirror"]["permissions"] == {"contents": "read", "packages": "write"}
    assert "secrets." not in text
    # The token is given to the login through the environment, never written into a command.
    login = next(
        s for s in workflow["jobs"]["mirror"]["steps"] if s.get("name") == "Log in to ghcr.io"
    )
    assert login["env"]["TOKEN"] == "${{ github.token }}"
    assert "github.token" not in login["run"] and "--password-stdin" in login["run"]


def test_the_mirror_starts_when_a_list_changes_weekly_and_on_demand():
    on = _mirror_workflow()[True]
    assert set(on) == {"push", "schedule", "workflow_dispatch"}
    assert ".github/ci-images/**" in on["push"]["paths"]
    assert on["push"]["branches"] == ["main", "ci/**"]
