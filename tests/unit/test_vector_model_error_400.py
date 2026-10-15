# Copyright (c) 2026 Kenneth Stott
# Canary: 97119b89-abf9-460d-a597-8dd67e465e89
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A vector model the statement cannot use is the caller's 400 naming it on every route: /data/sql
answered it so, and /data/graphql let it through to the catch-all's 500 "Internal server error"."""

from __future__ import annotations

import json

import pytest

from provisa.vector.registry import VectorModelError


@pytest.mark.asyncio
async def test_the_app_answers_a_vector_model_error_400_naming_the_model():
    from provisa.api.app import create_app

    refused = VectorModelError("Vector model 'mini' is not registered (allowlist).")
    handler = create_app().exception_handlers[VectorModelError]
    response = await handler(None, refused)  # type: ignore[arg-type]
    assert response.status_code == 400
    assert json.loads(response.body) == {
        "detail": "Vector model 'mini' is not registered (allowlist)."
    }
