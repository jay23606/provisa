# Copyright (c) 2026 Kenneth Stott
# Canary: 6a698f08-376d-4178-9ef5-5ae5e190aaae
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""The local test platform's Redis: fakeredis's TCP server, on a plain TCP address.

fakeredis is a base dependency. ``TcpFakeServer`` speaks the Redis protocol on a real TCP port, so
the production client (``redis`` / ``redis.asyncio``) connects to ``redis://127.0.0.1:port`` as it
would to a Redis server: no client-side fake, no container.

What it does not do: enforce ACL key patterns. ``ACL SETUSER``/``GETUSER``/``USERS``/``DELUSER``
are accepted and a created user can authenticate, so org provisioning (REQ-700/701) runs here, but
a user limited to ``~org_a:*`` can still write ``org_b:*``. A test that asserts that isolation is
on the CI side (real Redis).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class LocalRedis:
    """A running fakeredis TCP server on ``127.0.0.1:port``."""

    port: int
    server: Any
    thread: threading.Thread

    def url(self, db: int = 0) -> str:
        return f"redis://127.0.0.1:{self.port}/{db}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)


def start_local_redis(port: int) -> LocalRedis:
    """Serve fakeredis on ``127.0.0.1:port`` until :meth:`LocalRedis.stop`."""
    from fakeredis import TcpFakeServer

    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    thread = threading.Thread(target=server.serve_forever, name="local-redis", daemon=True)
    thread.start()
    return LocalRedis(port=port, server=server, thread=thread)
