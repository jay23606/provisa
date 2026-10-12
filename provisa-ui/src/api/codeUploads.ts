// Copyright (c) 2026 Kenneth Stott
// Canary: fab17cab-39a7-41d6-9014-dc633361ce76
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1984, REQ-1993: a code source's uploads -- an archive of its code, kept by the content hash
// of the code it unpacks to, and a lockfile given beside a package reference, kept by the SHA-256
// of its bytes (provisa/api/admin/code_uploads_router.py). The body is the file's bytes.

import { requestFailed, serverMessage } from "../i18n/serverMessage";

const API_BASE = import.meta.env.VITE_API_BASE || "";

async function ok<T>(res: Response, op: string): Promise<T> {
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(serverMessage(data, requestFailed(op, res.status)));
  }
  return res.json() as Promise<T>;
}

const url = (orgId: string, what: "archive" | "lockfile", filename: string) =>
  `${API_BASE}/admin/orgs/${encodeURIComponent(orgId)}/code-uploads/${what}?filename=${encodeURIComponent(filename)}`;

/** Keep an archive of code; the content hash of the code it unpacks to. */
export async function uploadCodeArchive(orgId: string, file: File): Promise<string> {
  const answered = await ok<{ content_hash: string }>(
    await fetch(url(orgId, "archive", file.name), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    }),
    "uploadCodeArchive",
  );
  return answered.content_hash;
}

/** Keep a lockfile given beside a package reference; the SHA-256 of its bytes. */
export async function uploadLockfile(orgId: string, file: File): Promise<string> {
  const answered = await ok<{ sha256: string }>(
    await fetch(url(orgId, "lockfile", file.name), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    }),
    "uploadLockfile",
  );
  return answered.sha256;
}
