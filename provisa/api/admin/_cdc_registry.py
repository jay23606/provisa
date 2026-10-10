# Copyright (c) 2026 Kenneth Stott
# Canary: 44684731-60cc-4500-9023-494070f57903
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Saving how a source's schema registry is reached (REQ-1951).

The settings are part of the source's CDC block. Saved with a source, they are refused by name
when they do not say how to reach the registry, and the credentials among them are kept as the
source's password is (REQ-1695): a literal goes into the org vault and the block holds the
reference that names it."""

from __future__ import annotations

from provisa.api.admin._row_mappers import _REGISTRY_FIELDS, _cdc_model_from_input
from provisa.api.admin.types import MutationResult, SourceInput
from provisa.kafka.avro_registry import (
    RegistrySettingRefused,
    validate_settings,
)

# Requirements: REQ-1951


def refuse_registry_settings(input: SourceInput) -> MutationResult | None:
    """The refusal for registry settings that do not say how to reach the registry, or None."""
    if input.cdc is None:
        return None
    fields = {name: getattr(input.cdc, name) for name in _REGISTRY_FIELDS}
    fields["schema_registry_url"] = input.cdc.schema_registry_url
    try:
        validate_settings(input.id, fields)
    except RegistrySettingRefused as refused:
        return MutationResult(
            success=False, message=str(refused), code=refused.code, params=refused.params
        )
    return None


async def stored_cdc(info, input: SourceInput):
    """The source's CDC block as the row holds it: each registry credential exactly as the
    operator entered it (a value, or a reference they typed), resolved where it is used."""
    return _cdc_model_from_input(input)
