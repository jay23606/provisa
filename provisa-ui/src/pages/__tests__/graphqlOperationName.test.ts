// Copyright (c) 2026 Kenneth Stott
// Canary: ad84462a-f17c-468a-a562-fd7d023a2839
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { describe, expect, it } from "vitest";
import { operationNameOf } from "../graphqlOperationName";

describe("a handed query's operation name", () => {
  it("is its first named operation, past its comments", () => {
    expect(
      operationNameOf(
        "# The slowest pages: each path, query by query\nquery SlowestPagesByPath {\n  a\n}",
      ),
    ).toBe("SlowestPagesByPath");
    expect(operationNameOf("mutation Save($x: Int) { save(x: $x) }")).toBe("Save");
  });

  it("is none for an anonymous query", () => {
    expect(operationNameOf("{ orders { id } }")).toBeNull();
    expect(operationNameOf("query { orders { id } }")).toBeNull();
  });
});
