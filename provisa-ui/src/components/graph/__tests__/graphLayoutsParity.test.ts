// Copyright (c) 2026 Kenneth Stott
// Canary: e6412371-bcd3-4e01-8876-afe0cabc9eba
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// @vitest-environment node

// The MCP server's render_graph hands a client the layout options the UI draws a graph with, from
// provisa/api/mcp/graph_layouts.json. They are the UI's own: a client running Cytoscape with them
// gets the picture the UI gives. This holds the file equal to the options the UI uses.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { LAYOUT_OPTIONS } from "../canvas/canvas-types";
import { ERD_ELK_LAYOUT } from "../../erd/erd-layout-options";

const served = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../../provisa/api/mcp/graph_layouts.json"), "utf8"),
) as Record<string, Record<string, unknown>>;

/** The options as a client receives them: an option the UI gives as a constant function is its value. */
function asServed(options: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(options).map(([k, v]) => [
      k,
      typeof v === "function" ? (v as () => unknown)() : v,
    ]),
  );
}

describe("the layouts render_graph serves", () => {
  it("are the graph page's force and hierarchy layouts", () => {
    expect(served.force).toEqual(asServed(LAYOUT_OPTIONS.force as Record<string, unknown>));
    expect(served.hierarchy).toEqual(asServed(LAYOUT_OPTIONS.hierarchy as Record<string, unknown>));
  });

  it("is the ERD's ELK layout", () => {
    expect(served.elk).toEqual(ERD_ELK_LAYOUT);
  });

  it("are those three, and no other", () => {
    expect(Object.keys(served).sort()).toEqual(["elk", "force", "hierarchy"]);
  });
});
