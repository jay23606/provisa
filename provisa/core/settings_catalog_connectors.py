# Copyright (c) 2026 Kenneth Stott
# Canary: 3aaa779c-9414-4941-89bf-2a761dde21f6
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Where each connector's bundled pgwire server is found, as operator settings (REQ-1954).

One setting per connector: a folder holding a bundle built for this host (its
``bin/pgwire-<connector>`` launcher), used as it is in place of the pinned release. Unset, the
pinned release is fetched (REQ-956). A folder without the launcher is refused by name when the
connector's server starts; the release is never fetched in its place.
"""

# Requirements: REQ-1954, REQ-956

from __future__ import annotations

from provisa.core.settings_registry import Setting
from provisa.runtime_deps.pgwire_bundles import BUNDLE_CONNECTOR, bundle_dir_key, bundle_dir_setting

DECLARED: list[Setting] = [
    Setting(
        key=bundle_dir_key(connector),
        card="connectors",
        type="str",
        effect="live",  # read each time the connector's server starts
        req="REQ-1954",
        env=bundle_dir_setting(connector),
        default=None,
        nullable=True,
    )
    for connector in sorted(set(BUNDLE_CONNECTOR.values()))
]
