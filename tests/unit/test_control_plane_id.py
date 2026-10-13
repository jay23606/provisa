# Copyright (c) 2026 Kenneth Stott
# Canary: 591449d0-719a-46ec-8f67-3177bdd82f11
#
# This source code is licensed under the Business Source License 1.1
"""REQ-2008: the control plane's id is created once, at its first start, and kept."""

from __future__ import annotations

import uuid

import pytest

from provisa.core import control_plane_id, deployment_settings


@pytest.fixture
def db(monkeypatch, control_plane):
    db = control_plane.platform
    monkeypatch.setattr(deployment_settings, "_db", db)
    monkeypatch.setattr(deployment_settings, "_held", None)
    return db


def test_the_first_start_creates_the_id_and_every_later_start_keeps_it(db):
    created = control_plane_id.ensure(db)
    assert str(uuid.UUID(created)) == created
    assert control_plane_id.ensure(db) == created
    assert control_plane_id.current() == created


def test_a_control_plane_with_no_id_is_refused_by_name(db):
    with pytest.raises(RuntimeError, match="the control plane has no id"):
        control_plane_id.current()
