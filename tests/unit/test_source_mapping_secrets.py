# Copyright (c) 2026 Kenneth Stott
# Canary: 2e9d5a74-b360-4c18-8f27-d1a6c0e9b453
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A credential typed into a source's mapping or its CDC block is kept as typed.

A SharePoint certificate password, a Salesforce security token, a cloud inventory's client
secret, a schema registry's password: each is a field of the source, and holds exactly what the
operator entered -- the value, or a ``${secret:NAME}`` / ``${env:NAME}`` reference they wrote.
It is resolved where it is used by the one resolver. Nothing is put in a vault for it and no
name is made up.
"""

from __future__ import annotations

import pytest

from provisa.core.secrets import resolve_secrets_in_dict


def test_a_mapping_is_resolved_field_by_field_by_the_one_resolver(monkeypatch):
    monkeypatch.setenv("PROVISA_TEST_SF_TOKEN", "tok-from-env")
    typed = {
        "auth_type": "USERNAME_PASSWORD",
        "sf_username": "ops@acme.com",
        "sf_password": "hunter2",  # a value: used as it is
        "security_token": "${env:PROVISA_TEST_SF_TOKEN}",  # a reference the operator typed
        "certificate_password": "",  # a password-less certificate names the empty string
    }
    assert resolve_secrets_in_dict(typed) == {
        **typed,
        "security_token": "tok-from-env",
    }
    assert typed["sf_password"] == "hunter2"  # what the row holds is not edited by a read


def test_a_typed_secret_reference_names_the_operators_own_secret():
    with pytest.raises(KeyError, match="my_pfx"):
        # No organisation's vault is bound here: the reference is theirs and is asked of theirs.
        resolve_secrets_in_dict({"certificate_password": "${secret:my_pfx}"})
