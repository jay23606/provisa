// Copyright (c) 2026 Kenneth Stott
// Canary: 5be0b5c5-d365-40d7-bbb0-47e2d127995d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1363: laying out the domain tree.

import { describe, it, expect } from "vitest";
import { alsoReached, descendantsOf } from "../lib/domainTree";

const DOMAINS = [
  { id: "retail_emea", parentDomainId: "retail" },
  { id: "finance", parentDomainId: null },
  { id: "retail", parentDomainId: null },
  { id: "retail_emea_uk", parentDomainId: "retail_emea" },
  { id: "retail_apac", parentDomainId: "retail" },
];

describe("domainTree (REQ-1363)", () => {
  it("lists every domain under one, at any depth", () => {
    expect(descendantsOf("retail", DOMAINS)).toEqual([
      "retail_apac",
      "retail_emea",
      "retail_emea_uk",
    ]);
    expect(descendantsOf("finance", DOMAINS)).toEqual([]);
  });

  it("names what a grant reaches beyond what it lists", () => {
    expect(alsoReached(["retail_emea"], DOMAINS)).toEqual(["retail_emea_uk"]);
    expect(alsoReached(["retail", "retail_emea"], DOMAINS)).toEqual([
      "retail_apac",
      "retail_emea_uk",
    ]);
    expect(alsoReached(["finance"], DOMAINS)).toEqual([]);
  });
});
