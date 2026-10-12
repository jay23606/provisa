// Copyright (c) 2026 Kenneth Stott
// Canary: c05bce3f-6a7b-4cfc-9e33-92e11c60f3c7
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// render_graph's renderer, one process per call: a DrawRequest as JSON on stdin, the PNG on
// stdout. A failure writes its reason to stderr and exits non-zero.

import { drawPng, type DrawRequest } from "./draw";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

try {
  const req = JSON.parse(await readStdin()) as DrawRequest;
  process.stdout.write(await drawPng(req));
} catch (e) {
  process.stderr.write(`${e instanceof Error ? e.message : String(e)}\n`);
  process.exitCode = 1;
}
