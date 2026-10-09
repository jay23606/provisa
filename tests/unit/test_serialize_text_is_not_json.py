# Copyright (c) 2026 Kenneth Stott
# Canary: 0b9e4f6a-71c3-4d2e-8a55-c3f1d7e2a9b4
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""A GraphQL result returns a text column's value as the text the source holds. Only a column
whose type is JSON is a JSON value (REQ-980, REQ-1965); a string that merely begins with ``[`` or
``{`` is a string."""

from __future__ import annotations

import pytest

from provisa.compiler.sql_gen import ColumnRef
from provisa.executor.serialize import serialize_rows

_COLUMNS = [
    ColumnRef(alias="t0", column="id", field_name="id", nested_in=None),
    ColumnRef(alias="t0", column="note", field_name="note", nested_in=None),
]


@pytest.mark.parametrize(
    "text",
    [
        '["draft"]',  # a tag a user typed
        "[1, 2]",  # an interval written as text
        '{"a": 1}',  # a template
        "{}",
        "[]",
        "[draft]",  # not JSON at all
        "{x}",
    ],
)
def test_a_text_value_that_looks_like_json_is_returned_as_the_text(text):
    out = serialize_rows([(1, text)], _COLUMNS, "notes")

    assert out == {"data": {"notes": [{"id": 1, "note": text}]}}
