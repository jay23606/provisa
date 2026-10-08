# Copyright (c) 2026 Kenneth Stott
# Canary: 6e1b9f47-3d02-4c85-a7e6-0f9d2c58b314
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A numeric column's precision and scale, as the model records them (REQ-1961).

The model records a decision: a numeric column either declares its precision and scale, and is
then exact everywhere it is read, or declares none and is floating point everywhere. The
declaration lives in the column's stored type, in one spelling — ``numeric(p,s)`` — written by
:func:`numeric_type` and read by :func:`numeric_size`. Nothing else writes or parses it.
"""

# Requirements: REQ-1961

from __future__ import annotations

import re

import pyarrow as pa

_SIZED = re.compile(r"^\s*(?:decimal|numeric)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*$", re.IGNORECASE)
_DECIMAL128_MAX_PRECISION = 38
_DECIMAL256_MAX_PRECISION = 76


class NumericSizeInvalid(ValueError):
    """A precision and scale that no numeric column can have."""

    def __init__(self, precision: object, scale: object) -> None:
        self.precision = precision
        self.scale = scale
        super().__init__(
            f"numeric({precision},{scale}) is not a numeric type: precision is 1 to "
            f"{_DECIMAL256_MAX_PRECISION} and scale is 0 to the precision"
        )


def require_numeric_size(precision: object, scale: object) -> tuple[int, int]:
    """(precision, scale) when they size a numeric column, else :class:`NumericSizeInvalid`."""
    if (
        isinstance(precision, bool)
        or isinstance(scale, bool)
        or not isinstance(precision, int)
        or not isinstance(scale, int)
        or not 0 < precision <= _DECIMAL256_MAX_PRECISION
        or not 0 <= scale <= precision
    ):
        raise NumericSizeInvalid(precision, scale)
    return precision, scale


def numeric_type(precision: int, scale: int) -> str:
    """The stored type of a numeric column that declares ``precision`` and ``scale``."""
    precision, scale = require_numeric_size(precision, scale)
    return f"numeric({precision},{scale})"


def numeric_size(data_type: str | None) -> tuple[int, int] | None:
    """The (precision, scale) a stored type declares, or None when it declares none — a bare
    ``numeric``, or a type that is not numeric at all."""
    sized = _SIZED.match(data_type) if data_type else None
    if sized is None:
        return None
    return require_numeric_size(int(sized[1]), int(sized[2]))


def numeric_arrow_type(data_type: str | None) -> pa.DataType:
    """The Arrow type a numeric column is read as, and listed under: exact where the model
    declares its size, floating point where it does not."""
    size = numeric_size(data_type)
    if size is None:
        return pa.float64()
    precision, scale = size
    if precision <= _DECIMAL128_MAX_PRECISION:
        return pa.decimal128(precision, scale)
    return pa.decimal256(precision, scale)
