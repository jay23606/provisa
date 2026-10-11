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
  /**
   * Whether people connect their own mailbox by signing in. It is not stored: an entry that
   * holds a client is one people can sign in with.
   */
  own_mailbox: boolean;
  /** The platform's own credential as typed: the value, or a reference to a secret. */
  organisation_key: string;
}

export const draftOf = (p: MailPlatform): Draft => ({
  client_id: p.client_id ?? "",
  // The field shows again what it holds: the value typed, or the reference typed.
  client_secret: p.client_secret ?? "",
  settings: Object.fromEntries(
    [...p.settings_fields, ...p.organisation_settings_fields].map((f) => [f, p.settings[f] ?? ""]),
  ),
  organisation_mailboxes: p.organisation_mailboxes,
  own_mailbox: p.client_id !== null,
  // The field shows again what it holds.
  organisation_key: p.organisation_key ?? "",
});

/**
 * Whether the entry is entered with a client. One person's sign-in always uses it; the
 * organisation's mailboxes use it where the platform declares no credential of its own for them.
 */
export const needsClient = (p: MailPlatform, draft: Draft): boolean =>
  draft.own_mailbox || (draft.organisation_mailboxes && !p.organisation_key_field);

/** What is still needed before a platform's entry can be saved, as the server has it. */
export function platformMissing(p: MailPlatform, draft: Draft): string[] {
  // Nothing chosen is nothing to save: an entry is never kept that nothing can read with.
  if (!draft.own_mailbox && !draft.organisation_mailboxes) return ["choice"];
  const missing: string[] = [];
  if (needsClient(p, draft)) {
    if (!draft.client_id.trim()) missing.push("client_id");
    if (!draft.client_secret) missing.push("client_secret");
  }
  for (const field of p.settings_fields) {
    if (!draft.settings[field]?.trim()) missing.push(field);
  }
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
