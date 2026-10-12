// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A detail panel's read view shows every value of its object, under the labels its edit form
// gives them. This guard reads each panel's edit form and read view and fails on a field the form
// labels that the read view does not: a value that can be set but not seen.

import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = resolve(__dirname, "../../..");

interface Panel {
  /** The files that draw the read view. */
  read: string[];
  /** The files that draw the edit form's fields. */
  form: string[];
  /** A form label the read view does not show as a field, with the reason. */
  notAField?: Readonly<Record<string, string>>;
}

/** Every list page's detail panel, by page. */
const PANELS: Readonly<Record<string, Panel>> = {
  Relationships: {
    read: ["components/relationships/RelationshipRead.tsx"],
    form: [
      "components/relationships/RelationshipDetail.tsx",
      "components/relationships/JunctionPanel.tsx",
    ],
  },
};

/** The catalog keys a file gives as a field's label: `label={t("key")}`. */
function formLabels(file: string): string[] {
  const text = readFileSync(resolve(SRC, file), "utf8");
  return [...text.matchAll(/(?<![-\w])label=\{t\("([^"]+)"/g)].map((m) => m[1]);
}

/** Every catalog key a file reads: `t("key")`. */
function keysRead(file: string): Set<string> {
  const text = readFileSync(resolve(SRC, file), "utf8");
  return new Set([...text.matchAll(/\bt\("([^"]+)"/g)].map((m) => m[1]));
}

describe("a detail panel's read view shows every field its edit form has", () => {
  for (const [page, panel] of Object.entries(PANELS)) {
    it(page, () => {
      for (const file of [...panel.read, ...panel.form]) {
        expect(existsSync(resolve(SRC, file)), file).toBe(true);
      }
      const labels = new Set(panel.form.flatMap(formLabels));
      expect(labels.size, "the form's labels were found").toBeGreaterThan(0);
      const shown = new Set(panel.read.flatMap((f) => [...keysRead(f)]));
      const exempt = panel.notAField ?? {};
      const missing = [...labels].filter((key) => !shown.has(key) && !(key in exempt));
      expect(missing, `${page}: set in the form, not shown in the read view`).toEqual([]);
      // An exemption names a label the form still has.
      expect(Object.keys(exempt).filter((key) => !labels.has(key))).toEqual([]);
    });
  }
});
