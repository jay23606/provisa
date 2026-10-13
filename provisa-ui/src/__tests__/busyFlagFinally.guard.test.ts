// Copyright (c) 2026 Kenneth Stott
// Canary: 08812be0-a5ca-4b4d-8f3d-169b6de2ee6f
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A busy flag set before an await is cleared in a `finally`. Every mutation wrapper of
// hooks/useAdminQueries.ts throws when the server answers with GraphQL errors, and a REST call
// throws when the network does: a flag cleared on the line after the await is then never cleared,
// and the button spins forever -- the relationship save that hung on a duplicate alias.
//
// A busy flag is a state setter named for what is under way (setSaving, setDeleting, setBusy,
// setSavingAlias, setPending...), set to a value and later cleared to false, null or "". The check
// reads the source between the two: an await there must be inside a try whose finally clears it.
// Those that are not busy flags, or are cleared another way on purpose, are listed with why.

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const SRC = resolve(__dirname, "..");

/** `<file> <setter>` -> why its flag is not cleared in a finally. */
const EXEMPT: Readonly<Record<string, string>> = {
  "pages/NlPage.tsx setSubmitting":
    "the submit is followed by a result stream, whose end and error callbacks clear it; a failed submit clears it in its catch",
  "components/admin/SettingField.tsx setPending":
    "the values awaiting a guarded setting's confirmation, not a busy flag",
  "pages/OnboardOrgPage.tsx setBreadthWarning": "a warning's text, not a busy flag",
  "pages/RelationshipsPage.tsx setSaving":
    "its three save handlers are being converted with the server's refusal (natural-key audit item 5)",
};

const BUSY =
  /\b(set(?!Editing)(?:[A-Z]\w*?(?:ing|Busy|Pending|InFlight)|(?:Saving|Loading|Running|Submitting|Deleting|Creating|Applying|Uploading|Refreshing|Toggling)[A-Z]\w*))\(\s*([^()]*?)\s*\)/g;
const CLEARED = new Set(["false", "null", '""', "''", "undefined"]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** `<file> <setter>` for each busy flag whose clear is not reached when an await before it throws. */
function unclearedOnThrow(): Set<string> {
  const found = new Set<string>();
  for (const path of sources(SRC)) {
    const file = relative(SRC, path).split("\\").join("/");
    const text = readFileSync(path, "utf8");
    const calls = [...text.matchAll(BUSY)].map((m) => ({
      at: m.index ?? 0,
      end: (m.index ?? 0) + m[0].length,
      setter: m[1],
      value: m[2],
    }));
    calls.forEach((call, i) => {
      if (CLEARED.has(call.value) || call.value.startsWith("(") || call.value.includes("=>")) {
        return;
      }
      const clear = calls
        .slice(i + 1)
        .find((c) => c.setter === call.setter && CLEARED.has(c.value));
      if (!clear) return;
      const between = text.slice(call.end, clear.at);
      if (/\bawait\b/.test(between) && !/\bfinally\b/.test(between)) {
        found.add(`${file} ${call.setter}`);
      }
    });
  }
  return found;
}

describe("a busy flag set before an await", () => {
  const found = unclearedOnThrow();

  it("is cleared in a finally, so a failed save frees its button", () => {
    expect([...found].filter((k) => !(k in EXEMPT)).sort()).toEqual([]);
  });

  it("an exemption names a flag the check still finds", () => {
    expect(Object.keys(EXEMPT).filter((k) => !found.has(k))).toEqual([]);
  });
});
