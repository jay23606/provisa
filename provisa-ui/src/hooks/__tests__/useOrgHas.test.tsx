// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2013: the tour reads what the org has once per start. Two starts in quick succession (the
// `?tour=1` path) each get their answer. A lazy query's execute aborts its call still in flight
// when it runs again; the first start was left rejected with "The operation was aborted" and the
// core tour never started (core e2e lane, 87d09e9c5).

import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { DataProductsQuery, SourcesQuery, TablesQuery } from "../admin.graphql";

const answers = new Map<unknown, unknown>([
  [SourcesQuery, { sources: [{ id: "shop-db" }] }],
  [TablesQuery, { tables: [{ sourceId: "shop-db", tableName: "orders" }] }],
  [DataProductsQuery, { dataProducts: [{ id: "p1" }] }],
]);
const executed: unknown[] = [];

/** A lazy query as Apollo's behaves here: executing it again aborts the execution in flight. */
function lazy(document: unknown) {
  let pending: ((e: Error) => void) | null = null;
  const execute = () => {
    executed.push(document);
    pending?.(new DOMException("The operation was aborted.", "AbortError"));
    return new Promise((resolve, reject) => {
      pending = reject;
      setTimeout(() => {
        pending = null;
        resolve({ data: answers.get(document) });
      }, 5);
    });
  };
  return [execute];
}

vi.mock("@apollo/client/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@apollo/client/react")>();
  const made = new Map<unknown, unknown>();
  return {
    ...actual,
    useLazyQuery: (document: unknown) => {
      if (!made.has(document)) made.set(document, lazy(document));
      return made.get(document);
    },
  };
});

const { useOrgHas } = await import("../useOrgHas");

describe("what the org has, read for the tour", () => {
  it("answers both of two reads made at once", async () => {
    const { result } = renderHook(() => useOrgHas());
    const [first, second] = await Promise.all([result.current(), result.current()]);
    for (const has of [first, second]) {
      expect([...has.sources]).toEqual(["shop-db"]);
      expect([...has.tables]).toEqual(["shop-db.orders"]);
      expect(has.dataProducts).toBe(1);
    }
    expect(executed).toHaveLength(3); // one read, shared
  });

  it("reads again once the last read has answered", async () => {
    executed.length = 0;
    const { result } = renderHook(() => useOrgHas());
    await result.current();
    await result.current();
    expect(executed).toHaveLength(6);
  });
});
