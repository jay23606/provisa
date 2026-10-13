# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The control plane's id (REQ-2008): a UUID the platform control plane creates at its first start
and keeps, the same for every node and worker. The UI scopes what it saves in the browser by it, so
two control planes reached from one browser (two demos, two instances) keep their state apart. A
new control plane (a pristine demo start) is a new id.

Stored as the ``deployment_settings`` row ``control_plane.id``, created the way the platform fake
key is (``provisa.fakes.platform_key``): the first start stores it, a concurrent one meets that row.
"""

# Requirements: REQ-2008

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from provisa.core.database import Database

SETTING = "control_plane.id"


def ensure(db: "Database") -> str:
    """The control plane's id, created now when it has none."""
    from provisa.core import deployment_settings

    if deployment_settings.get(SETTING) is None:
        deployment_settings.create(db, SETTING, str(uuid.uuid4()), updated_by="platform")
    return current()


def current() -> str:
    """The id of the control plane this process is bound to; created at start by :func:`ensure`."""
    from provisa.core import deployment_settings

    held = deployment_settings.get(SETTING)
    if held is None:
        raise RuntimeError("the control plane has no id: the platform start did not create it")
    return held
