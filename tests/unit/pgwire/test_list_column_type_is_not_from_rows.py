# Copyright (c) 2026 Kenneth Stott
# Canary: 4e2a8c15-9d07-4b6f-a3e1-7c5d0f8b2a61
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""REQ-1965, REQ-1961: the type a wire lists for a column is the column's, not a reading of the
rows one result happens to return. Two results of the same list column are typed the same."""

from __future__ import annotations

import pytest

from provisa.pgwire.server import _infer_bvtype

# Results of ONE column, ``tags`` (a list of text), that differ only in the rows returned.
_RESULTS = {
    "a tag first": [(["a", "b"],), ([],)],
    "an empty list first": [([],), (["a", "b"],)],
    "only empty lists": [([],), ([],)],
    "only nulls": [(None,), (None,)],
    "no rows": [],
}


@pytest.mark.parametrize("other", [k for k in _RESULTS if k != "a tag first"])
def test_a_list_column_is_typed_the_same_whatever_rows_a_result_returns(other):
    assert _infer_bvtype(_RESULTS[other], 0) == _infer_bvtype(_RESULTS["a tag first"], 0)


def test_a_list_column_of_integers_and_one_of_text_are_the_same_wire_type():
    """Semantic SQL has no array type: every natively nested column is JSON on the wire."""
    assert _infer_bvtype([([1, 2],)], 0) == _infer_bvtype([(["a"],)], 0)
