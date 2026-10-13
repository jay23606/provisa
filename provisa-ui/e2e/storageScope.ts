// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import type { APIRequestContext } from "@playwright/test";
import { BACKEND_URL } from "./coverage";

/**
 * REQ-2008: the key the app saves `key` under in the browser — `<control plane id>:<org id>:<key>`
 * (src/lib/browserStorage.ts) — for the server under test, read from /auth/me as the app's scope
 * gate reads it. A spec that seeds the app's saved state writes it here.
 */
export async function scopedStorageKey(request: APIRequestContext, key: string): Promise<string> {
  const res = await request.get(`${BACKEND_URL}/auth/me`);
  if (!res.ok()) throw new Error(`/auth/me answered ${res.status()}: ${await res.text()}`);
  const me = (await res.json()) as {
    control_plane_id: string;
    active_org_id: string | null;
    org_memberships: { org_id: string }[];
  };
  const org =
    me.active_org_id ?? (me.org_memberships.length === 1 ? me.org_memberships[0].org_id : "");
  return `${me.control_plane_id}:${org}:${key}`;
}
