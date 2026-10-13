// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2008: every read and write of the browser's storage goes through lib/browserStorage, which
// saves it per control plane and org unless the key is marked global. A component that reached
// localStorage or sessionStorage itself would carry its state from one demo, instance or org into
// the next.

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const SRC = resolve(__dirname, "..");
const HELPER = "lib/browserStorage.ts";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** The code of a file without its comments, which talk about localStorage freely. */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

// `localStorageColorSchemeManager` is Mantine's own manager of the color scheme, a global key.
const DIRECT = /(?<![A-Za-z_$])(?:window\.)?(?:localStorage|sessionStorage)(?![A-Za-z_$])/;

describe("the browser's storage is reached through lib/browserStorage only", () => {
  it("no file but the helper reads or writes localStorage or sessionStorage", () => {
    const direct = sources(SRC)
      .map((path) => ({ file: relative(SRC, path).split("\\").join("/"), path }))
      .filter(({ file }) => file !== HELPER)
      .filter(({ path }) => DIRECT.test(code(readFileSync(path, "utf8"))))
      .map(({ file }) => file);
    expect(direct).toEqual([]);
  });
});
