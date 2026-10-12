# Copyright (c) 2026 Kenneth Stott
# Canary: e63da40e-2c10-40ef-91c7-3c0b6ee764f5
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""Vector query helpers (REQ-429, REQ-430).

- vectorize_text: embed a text query with an embedding model (REQ-430).
- validate_vector_dimensions: a vector has its model's dimensions (REQ-429).

A ``cosine_similarity`` search is governed, bound and lowered by ``provisa.vector.similarity``.
"""

from __future__ import annotations

from provisa.vector.registry import VectorModel, VectorModelError

# Requirements: REQ-429, REQ-430


class VectorQueryError(ValueError):
    """A vector query is malformed, or has no native translation."""


def validate_vector_dimensions(vector: list[float], model: VectorModel) -> None:  # REQ-429
    """Reject a query vector whose dimension does not match the model (REQ-429)."""
    if len(vector) != model.dimensions:
        raise VectorModelError(
            f"query vector has {len(vector)} dimensions; model {model.id!r} expects "
            f"{model.dimensions}"
        )


async def vectorize_text(text: str, model: VectorModel, provider=None) -> list[float]:  # REQ-430
    """Embed a text query into a vector using the model's provider (REQ-430)."""
    if provider is None:
        from provisa.vector.providers import get_provider

        provider = get_provider(model.provider)
    vecs = await provider.embed([text], model)
    if not vecs:
        raise VectorQueryError("provider returned no embedding")
    return vecs[0]
