# Copyright (c) 2026 Kenneth Stott
# Canary: 2f1d90b4-77ac-4e2b-9c05-6b1e4a83d2f7
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A control-plane source row carries its password as the operator entered it, and reads it back.

``sources.password_ref`` holds the text typed into the field: the value itself, or a
``${secret:NAME}`` / ``${env:NAME}`` reference the operator wrote. It is resolved where it is
used by the one resolver; nothing derives a name for it or stores it anywhere else. The mapper
below is the one place the column name and the model field name are tied together.
"""

from __future__ import annotations

import pytest

from provisa.core.models import Source, SourceType
from provisa.core.repositories.source import _source_values, source_from_row
from provisa.core.schema_org import sources as sources_table


def test_write_projection_carries_the_password_as_password_ref():
    values = _source_values(
        Source(
            id="splunk-demo",
            type=SourceType.splunk,
            host="localhost",
            port=8089,
            password="${secret:source_splunk_demo_password}",
        )
    )
    assert values["password_ref"] == "${secret:source_splunk_demo_password}"
    # One column holds what was entered; the model's field is its name there.
    assert "password" not in values


def test_password_ref_is_a_real_column_on_the_sources_table():
    assert "password_ref" in sources_table.c
    column = sources_table.c.password_ref
    assert column.nullable is False
    # A source that needs no password stores the empty string, so no reader deals with NULL.
    assert column.server_default.arg == ""


@pytest.mark.parametrize(
    "password",
    ["", "hunter2", "${env:PROVISA_DEMO_SPLUNK_PASSWORD}", "${secret:my_splunk_password}"],
)
def test_row_round_trip_preserves_what_was_typed(password):
    original = Source(
        id="ui_splunk",
        type=SourceType.splunk,
        host="localhost",
        port=8089,
        username="admin",
        password=password,
    )
    # A row as the control plane hands it back: the write projection plus the columns the table
    # defaults, which the mapper ignores because they are not model fields.
    row = {**_source_values(original), "binding": "own", "cache_enabled": True}
    assert source_from_row(row).password == password


def test_the_mapper_refuses_a_row_with_no_password_ref():
    """A row missing the column is a broken read, not a source without a password.

    The column is NOT NULL with an empty-string default, so every real row has it. Reading it with
    a default would turn a mis-projected SELECT into a source that silently authenticates with
    nothing -- exactly the failure REQ-1695 exists to end.
    """
    with pytest.raises(KeyError):
        source_from_row({"id": "x", "type": "splunk"})


# --- the credential is what was typed; nothing is named or stored on the operator's behalf ---


@pytest.mark.parametrize(
    ("typed", "used"),
    [
        ("hunter2", "hunter2"),  # a value is used as it is
        ("", ""),  # a source that needs no password
        ("${env:PROVISA_TEST_SOURCE_PASSWORD}", "from-the-environment"),
    ],
)
def test_what_was_typed_is_resolved_by_the_one_resolver(typed, used, monkeypatch):
    from provisa.core.secrets import resolve_secrets

    monkeypatch.setenv("PROVISA_TEST_SOURCE_PASSWORD", "from-the-environment")
    row = {**_source_values(_source(typed)), "binding": "own", "cache_enabled": True}
    assert row["password_ref"] == typed  # the row holds the text entered
    assert resolve_secrets(source_from_row(row).password) == used


def test_a_typed_secret_reference_is_the_operators_own_name_and_needs_their_vault():
    from provisa.core.secrets import resolve_secrets

    row = _source_values(_source("${secret:my_own_name}"))
    assert row["password_ref"] == "${secret:my_own_name}"
    with pytest.raises(KeyError, match="my_own_name"):
        resolve_secrets(row["password_ref"])  # no organisation's vault is bound here


def test_nothing_derives_a_secret_name_from_a_source():
    """The builders of ``source_<id>_password`` and its mapping-key variant are gone, with the
    vault write they named entries for."""
    from provisa.api.admin import schema_common

    for gone in (
        "source_password_secret_name",
        "source_mapping_secret_name",
        "persist_source_password",
        "store_source_password",
        "store_source_mapping_secrets",
        "forget_source_password",
        "forget_source_mapping_secrets",
        "_store_source_secret",
        "_forget_source_secret",
    ):
        assert not hasattr(schema_common, gone), gone


def _source(password: str) -> Source:
    return Source(
        id="ui_splunk",
        type=SourceType.splunk,
        host="localhost",
        port=8089,
        username="admin",
        password=password,
    )
