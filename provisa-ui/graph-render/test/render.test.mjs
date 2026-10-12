// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The renderer as the MCP server runs it: a request on stdin, a PNG on stdout, one process per
// call. Run after `npm run build`.

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createCanvas, loadImage } from "canvas";

const RENDER = fileURLToPath(new URL("../dist/render.mjs", import.meta.url));
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const elements = {
  nodes: [
    { data: { id: "Sales:Customer:1", label: "Sales:Customer", properties: { name: "Ada" } } },
    { data: { id: "Sales:Order:7", label: "Sales:Order", properties: { total: 10.5 } } },
    { data: { id: "Sales:Order:8", label: "Sales:Order", properties: { total: 3 } } },
  ],
  edges: [
    {
      data: {
        id: "70",
        source: "Sales:Customer:1",
        target: "Sales:Order:7",
        label: "PLACED",
        properties: {},
      },
    },
    {
      data: {
        id: "71",
        source: "Sales:Customer:1",
        target: "Sales:Order:8",
        label: "PLACED",
        properties: {},
      },
    },
  ],
};

function render(request) {
  return spawnSync(process.execPath, [RENDER], { input: JSON.stringify(request), timeout: 60_000 });
}

async function cornerPixel(png) {
  const image = await loadImage(png);
  const canvas = createCanvas(image.width, image.height);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

for (const layout of ["force", "hierarchy", "elk"]) {
  for (const [theme, background] of [
    ["light", "#ffffff"],
    ["dark", "#0f1117"],
  ]) {
    test(`${layout} on ${theme}: a PNG on the page's background for the theme`, async () => {
      const out = render({ elements, layout, theme, width: 800, height: 600 });
      assert.equal(out.status, 0, out.stderr.toString());
      assert.deepEqual(out.stdout.subarray(0, 8), PNG_SIGNATURE);
      assert.equal(await cornerPixel(out.stdout), background);
    });
  }
}

test("an unknown layout or theme fails, saying which", () => {
  for (const [request, says] of [
    [
      { elements, layout: "circle", theme: "light", width: 100, height: 100 },
      /unknown layout "circle"/,
    ],
    [
      { elements, layout: "force", theme: "sepia", width: 100, height: 100 },
      /unknown theme "sepia"/,
    ],
  ]) {
    const out = render(request);
    assert.notEqual(out.status, 0);
    assert.match(out.stderr.toString(), says);
  }
});

test("a node whose id is not <label>:<id> fails, naming it", () => {
  const bad = {
    nodes: [{ data: { id: "x", label: "Sales:Customer", properties: {} } }],
    edges: [],
  };
  const out = render({ elements: bad, layout: "force", theme: "light", width: 100, height: 100 });
  assert.notEqual(out.status, 0);
  assert.match(out.stderr.toString(), /node "x" is not <label>:<id>/);
});
