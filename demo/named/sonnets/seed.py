# Copyright (c) 2026 Kenneth Stott
# Canary: b19dfc5d-1105-417b-8048-d908f3d13936
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The sonnets demo's vector store (REQ-2016): the `seeder` service creates the empty Qdrant
collection the lines' embeddings are written to -- one named vector, ``text``, of the 384
dimensions sentence-transformers/all-MiniLM-L6-v2 gives, compared by cosine. Provisa's
embed_lines command fills it (setup.yaml). A collection already there is left as it is."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

QDRANT = os.environ["QDRANT_URL"]
COLLECTION = "sonnet_lines"
SPEC = {"vectors": {"text": {"size": 384, "distance": "Cosine"}}}


def _call(method: str, path: str, body: dict | None = None) -> int:
    request = urllib.request.Request(
        f"{QDRANT}{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    if _call("GET", f"/collections/{COLLECTION}") == 200:
        print(f"collection {COLLECTION} is there; nothing to do")
        return 0
    status = _call("PUT", f"/collections/{COLLECTION}", SPEC)
    if status != 200:
        print(f"creating collection {COLLECTION} failed: HTTP {status}", file=sys.stderr)
        return 1
    print(f"created collection {COLLECTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
