// Copyright (c) 2026 Kenneth Stott
// Canary: bde39cef-30e2-417f-abf4-e896d71ec058
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1923: what an administrator is typing for one mail platform, and what is still missing.

import type { MailPlatform } from "../../api/mailPlatforms";

export interface Draft {
  client_id: string;
  client_secret: string;
  settings: Record<string, string>;
  organisation_mailboxes: boolean;
  /** The platform's own credential as typed: the value, or a reference to a secret. */
  organisation_key: string;
}

export const draftOf = (p: MailPlatform): Draft => ({
  client_id: p.client_id ?? "",
  client_secret: "",
  settings: Object.fromEntries(
    [...p.settings_fields, ...p.organisation_settings_fields].map((f) => [f, p.settings[f] ?? ""]),
  ),
  organisation_mailboxes: p.organisation_mailboxes,
  // The field shows again what it holds.
  organisation_key: p.organisation_key ?? "",
});

/** Whether the organisation's entry holds a client, whose secret is then kept in its vault. */
export const clientEntered = (p: MailPlatform): boolean => p.configured && p.client_id !== null;

/** What is still needed before a platform's client can be saved. */
export function platformMissing(p: MailPlatform, draft: Draft): string[] {
  const missing: string[] = [];
  // A platform that reads the organisation's mailboxes with a credential of its own needs no
  // client once such sources are allowed: the client is for one person's sign-in.
  const noClient =
    p.organisation_key_field &&
    draft.organisation_mailboxes &&
    !draft.client_id.trim() &&
    !draft.client_secret;
  if (!noClient) {
    if (!draft.client_id.trim()) missing.push("client_id");
    if (!clientEntered(p) && !draft.client_secret) missing.push("client_secret");
  }
  for (const field of p.settings_fields) {
    if (!draft.settings[field]?.trim()) missing.push(field);
  }
  // Needed once sources that read the organisation's mailboxes are allowed, as the server has it.
  if (draft.organisation_mailboxes) {
    for (const field of p.organisation_settings_fields) {
      if (!draft.settings[field]?.trim()) missing.push(field);
    }
    if (p.organisation_key_field && !draft.organisation_key.trim()) {
      missing.push("organisation_key");
    }
  }
  return missing;
}
