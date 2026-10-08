# Copyright (c) 2026 Kenneth Stott
# Canary: b3f81c26-7a49-4e05-9d1b-52c6e0a94f73
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A numeric column's recorded precision and scale: one stored spelling, one writer, one reader."""

# Requirements: REQ-1961

from __future__ import annotations

import pyarrow as pa
import pytest
from sqlalchemy import Numeric

from provisa.core.ir_types import to_ir, to_sqlalchemy
from provisa.core.numeric_type import (
    NumericSizeInvalid,
    numeric_arrow_type,
    numeric_size,
    numeric_type,
)


def test_the_stored_form_is_one_spelling_and_reads_back():
    assert numeric_type(18, 2) == "numeric(18,2)"
    assert numeric_size(numeric_type(18, 2)) == (18, 2)
    assert numeric_size(numeric_type(5, 0)) == (5, 0)


@pytest.mark.parametrize("bare", ["numeric", "decimal", "NUMERIC", "integer", "varchar(20)", None])
def test_a_type_that_declares_no_size_has_none(bare):
    assert numeric_size(bare) is None


@pytest.mark.parametrize("spelling", ["decimal(10,2)", "DECIMAL(10, 2)", " numeric ( 10 , 2 ) "])
def test_a_declared_size_is_read_whatever_the_spelling_it_was_typed_in(spelling):
    assert numeric_size(spelling) == (10, 2)


@pytest.mark.parametrize("precision, scale", [(0, 0), (-1, 0), (10, 11), (10, -1), (77, 0)])
def test_a_size_no_numeric_column_can_have_is_refused(precision, scale):
    with pytest.raises(NumericSizeInvalid, match="precision is 1 to 76 and scale is 0 to"):
        numeric_type(precision, scale)


def test_a_non_integer_size_is_refused():
    for precision, scale in ((True, 0), ("10", 2), (10.0, 2), (10, None)):
        with pytest.raises(NumericSizeInvalid):
            numeric_type(precision, scale)  # type: ignore[arg-type]


def test_a_declared_numeric_is_exact_and_an_undeclared_one_is_floating_point():
    assert numeric_arrow_type("numeric(18,2)") == pa.decimal128(18, 2)
    assert numeric_arrow_type("numeric(38,10)") == pa.decimal128(38, 10)
    assert numeric_arrow_type("numeric(50,4)") == pa.decimal256(50, 4)
    assert numeric_arrow_type("numeric") == pa.float64()
    assert numeric_arrow_type("decimal") == pa.float64()


def test_the_vocabulary_and_the_store_ddl_read_the_same_declaration():
    assert to_ir(numeric_type(18, 2)) == "numeric"
    sized = to_sqlalchemy(numeric_type(18, 2))
    assert isinstance(sized, Numeric) and (sized.precision, sized.scale) == (18, 2)
    assert to_sqlalchemy("numeric") is Numeric
