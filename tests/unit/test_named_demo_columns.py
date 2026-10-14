# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Every column of a named demo's tables and views loads whole: a flow-mapping description holding
an unquoted ", <words>," is read as the description up to the comma and a key named by the rest,
which the column's model ignores, so the description shown is cut short."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from provisa.core.models import Column

_NAMED = Path(__file__).resolve().parents[2] / "demo" / "named"
CONFIGS = sorted(_NAMED.glob("*/config.yaml"))
_FIELDS = set(Column.model_fields) | {
    f.alias for f in Column.model_fields.values() if f.alias is not None
}


@pytest.mark.parametrize("path", CONFIGS, ids=[p.parent.name for p in CONFIGS])
def test_every_column_of_a_named_demo_loads_whole(path):
    config = yaml.safe_load(path.read_text())
    stray = [
        (relation.get("table") or relation["id"], column["name"], sorted(set(column) - _FIELDS))
        for relation in config.get("tables", []) + config.get("views", [])
        for column in relation.get("columns", [])
        if set(column) - _FIELDS
    ]
    assert stray == [], f"{path.parent.name}: keys no column has, from an unquoted comma: {stray}"


def test_an_unquoted_comma_in_a_description_is_caught():
    column = yaml.safe_load(
        "{name: c, description: The signed-in customer, from the cookie, visible_to: [a]}"
    )
    assert set(column) - _FIELDS == {"from the cookie"}
