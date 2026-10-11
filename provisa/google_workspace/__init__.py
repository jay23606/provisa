# Copyright (c) 2026 Kenneth Stott
# Canary: 60063fa4-2258-4ad6-a523-87f0de921ba4
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Google Workspace source: the mail, calendar and tasks of Google accounts (REQ-1923)."""

from provisa.core import mail_platforms

#: The source type's name, as a source row records it.
SOURCE_TYPE = "google_workspace"

# REQ-1923: an organisation enters its Google client once; every source of one mailbox signs in
# with it. Sources of the organisation's mailboxes read with a service account the domain has
# delegated to: its key, and the administrator address directory calls are made as.
#: The scopes a super administrator authorises the service account's client ID for: reading
#: mail, and listing the domain's users and a group's members (Directory API users.list,
#: members.list). A source that reads headers and labels only asks for gmail.metadata instead.
DELEGATED_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
)
mail_platforms.declare(
    mail_platforms.Platform(
        SOURCE_TYPE,
        organisation_settings=("admin_address",),
        organisation_key=True,
        organisation_scopes=DELEGATED_SCOPES,
    )
)
