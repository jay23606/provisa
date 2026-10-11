# Copyright (c) 2026 Kenneth Stott
# Canary: 81719129-a916-49ab-a373-0bbc355c3f0d
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Compile .proto content to Python stubs using grpc_tools.protoc."""

# Requirements: REQ-045, REQ-051
from __future__ import annotations

import tempfile
from pathlib import Path

from grpc_tools import protoc


def compile_descriptor_set(proto_content: str) -> bytes:
    """``proto_content`` compiled to a serialized ``FileDescriptorSet``, its imports included
    (the well-known types a service names). No Python module is generated: the caller loads the
    set into a descriptor pool of its own (grpc/descriptor.py)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "provisa_service.proto").write_text(proto_content)
        import grpc_tools

        well_known = str(Path(grpc_tools.__file__).parent / "_proto")
        out = Path(tmpdir) / "provisa_service.desc"
        result = protoc.main(
            [
                "grpc_tools.protoc",
                f"--proto_path={tmpdir}",
                f"--proto_path={well_known}",
                f"--descriptor_set_out={out}",
                "--include_imports",
                "provisa_service.proto",
            ]
        )
        if result != 0:
            raise RuntimeError(f"protoc compilation failed with code {result}")
        return out.read_bytes()
