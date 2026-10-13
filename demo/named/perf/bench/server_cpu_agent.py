# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The server's CPU, read from another host (REQ-1911).

The benchmark measures Provisa's CPU per request from the server process's cumulative CPU time at
the start and end of each step. ``--server-pid`` reads it locally, so the load generator must run
on the server's host. Started on the server's host, this agent answers that one figure over HTTP,
and a load generator elsewhere reads it with ``--server-cpu-url``.

It is read-only: ``GET /`` answers ``{"pid": N, "cpu_seconds": S}``, the user and system CPU
seconds of the process and all its descendants (its workers); every other path is 404 and every
other method is refused. It listens only where ``--listen`` says; there is no default address.

    python server_cpu_agent.py --pid 12345 --listen 10.0.0.5:9555
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def cpu_seconds(pid: int) -> float:
    """CPU the process ``pid`` has used so far: it and every descendant (its workers)."""
    import psutil

    root = psutil.Process(pid)
    total = 0.0
    for proc in [root, *root.children(recursive=True)]:
        try:
            times = proc.cpu_times()
        except psutil.NoSuchProcess:
            continue
        total += times.user + times.system
    return total


def handler(pid: int) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the http.server hook's name
            if self.path != "/":
                self.send_error(404)
                return
            body = json.dumps({"pid": pid, "cpu_seconds": cpu_seconds(pid)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return  # one request per step boundary: nothing worth logging

    return _Handler


def parse_listen(value: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"--listen must be HOST:PORT, got {value!r}")
    return host.strip("[]"), int(port)


def serve(pid: int, listen: tuple[str, int]) -> ThreadingHTTPServer:
    cpu_seconds(pid)  # refuse a pid that is not there before listening
    return ThreadingHTTPServer(listen, handler(pid))


def main() -> int:
    parser = argparse.ArgumentParser(description="Answer a process's cumulative CPU seconds")
    parser.add_argument("--pid", type=int, required=True, help="the Provisa server's process id")
    parser.add_argument(
        "--listen",
        type=parse_listen,
        required=True,
        help="HOST:PORT to listen on: a private address the load generator can reach",
    )
    args = parser.parse_args()
    server = serve(args.pid, args.listen)
    host, port = server.server_address[:2]
    print(f"server CPU of pid {args.pid} at http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
