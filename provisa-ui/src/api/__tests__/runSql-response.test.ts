// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// /data/sql answers a statement in one of two shapes: its rows with their columns, or a handle to
// the results store when the result was landed there (`{"data":{"sql":null},"redirect":{…}}`).
// runSql says which it is; it never hands a caller rows and columns it did not get.

import { afterEach, describe, expect, it, vi } from "vitest";
import { runSql } from "../admin";

function answer(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("runSql — what /data/sql answered", () => {
  it("returns the rows and their columns", async () => {
    answer({ data: { sql: [{ id: 1 }] }, columns: ["id"], column_types: ["integer"] });
    const r = await runSql("SELECT 1");
    expect(r.error).toBeUndefined();
    expect(r.redirect).toBeUndefined();
    expect(r.columns).toEqual(["id"]);
    expect(r.rows).toEqual([{ id: 1 }]);
  });

  it("says the result was landed in the results store, with where and how many rows", async () => {
    answer({
      data: { sql: null },
      redirect: {
        redirect_url: "https://results.example/r/abc.parquet",
        row_count: 2500000,
        expires_in: 3600,
        content_type: "application/vnd.apache.parquet",
      },
    });
    const r = await runSql("SELECT * FROM big");
    expect(r.error).toBeUndefined();
    expect(r.redirect).toEqual({
      url: "https://results.example/r/abc.parquet",
      rowCount: 2500000,
      expiresIn: 3600,
      contentType: "application/vnd.apache.parquet",
    });
    expect(r.rows).toEqual([]);
    expect(r.columns).toEqual([]);
  });

  it("fails loud when the answer carries no column list, never handing on an undefined one", async () => {
    answer({ data: { sql: [] }, detail: "the engine returned no description" });
    const r = await runSql("SELECT 1");
    expect(r.columns).toEqual([]);
    expect(r.error).toContain("the engine returned no description");
  });
});
