// Copyright (c) 2026 Kenneth Stott
// Canary: d31da747-9529-462d-bcaa-3a7312a74551
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The role form says what a domain grant also reaches down the domain tree (REQ-1363).

import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../../test-utils/render";
import { SubtreeNote } from "../security/RoleFormParts";

const DOMAINS = [
  { id: "retail", parentDomainId: null },
  { id: "sales", parentDomainId: "retail" },
  { id: "outlets", parentDomainId: "sales" },
  { id: "finance", parentDomainId: null },
];

describe("SubtreeNote", () => {
  it("names every domain under the ones granted", () => {
    render(<SubtreeNote listed={["retail"]} domains={DOMAINS} />);
    expect(screen.getByTestId("role-domain-subtree")).toHaveTextContent("outlets, sales");
  });

  it("says nothing when the grant reaches no more than it lists", () => {
    render(<SubtreeNote listed={["finance"]} domains={DOMAINS} />);
    expect(screen.queryByTestId("role-domain-subtree")).toBeNull();
  });

  it("says nothing for every domain", () => {
    render(<SubtreeNote listed={["*"]} domains={DOMAINS} />);
    expect(screen.queryByTestId("role-domain-subtree")).toBeNull();
  });
});
