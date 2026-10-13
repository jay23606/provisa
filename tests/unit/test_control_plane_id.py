# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-2008: the control plane's id is created once, at its first start, and kept."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine

from provisa.core import control_plane_id, deployment_settings
from provisa.core.schema_admin import deployment_settings as table


class _Db:
    def __init__(self, engine):
        self.engine = engine


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cp.db'}")
    table.create(engine)
    db = _Db(engine)
    monkeypatch.setattr(deployment_settings, "_db", db)
    monkeypatch.setattr(deployment_settings, "_held", None)
    # The settings stamp the snapshot is loaded with; this test's control plane holds no stamp table.
    monkeypatch.setattr(deployment_settings.config_stamp, "read_sync", lambda _db: {"settings": 0})
    return db


def test_the_first_start_creates_the_id_and_every_later_start_keeps_it(db):
    created = control_plane_id.ensure(db)
    assert str(uuid.UUID(created)) == created
    assert control_plane_id.ensure(db) == created
    assert control_plane_id.current() == created


def test_a_control_plane_with_no_id_is_refused_by_name(db):
    with pytest.raises(RuntimeError, match="the control plane has no id"):
        control_plane_id.current()
