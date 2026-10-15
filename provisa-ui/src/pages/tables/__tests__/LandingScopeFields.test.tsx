// Copyright (c) 2026 Kenneth Stott
// Canary: bc6dddbe-d277-4b9e-8b49-27b9d8c936fe
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useState } from "react";
import { describe, it, expect } from "vitest";
import { renderInForm, screen, fireEvent } from "../../../test-utils/render";
import { LandingScopeFields } from "../LandingScopeFields";
import type { RegisteredTable, Source } from "../../../types/admin";

const seen: { table: RegisteredTable | null } = { table: null };

function Harness({ type, table }: { type: string; table: Partial<RegisteredTable> }) {
  const [tbl, setTbl] = useState<RegisteredTable>(table as RegisteredTable);
  return (
    <LandingScopeFields
      editingTable={tbl}
      setEditingTable={(next) => {
        seen.table = next;
        setTbl(next);
      }}
      source={{ id: "s", type } as Source}
    />
  );
}

describe("LandingScopeFields (REQ-2061, REQ-2062)", () => {
  it("edits the landing filter on any table and clears it to none", () => {
    renderInForm(<Harness type="govdata" table={{ landingFilter: null }} />);
    const input = screen.getByTestId("landing-filter-input");
    fireEvent.change(input, { target: { value: "cvss >= 9" } });
    expect(seen.table?.landingFilter).toBe("cvss >= 9");
    fireEvent.change(input, { target: { value: "" } });
    expect(seen.table?.landingFilter).toBeNull();
  });

  it("offers fixed arguments only on a source that takes them by name", () => {
    renderInForm(<Harness type="postgresql" table={{}} />);
    expect(screen.queryByTestId("fixed-arguments-input")).toBeNull();
  });

  it("takes a JSON object of arguments and refuses anything else", () => {
    renderInForm(<Harness type="openapi" table={{ arguments: { org: "acme" } }} />);
    const input = screen.getByTestId("fixed-arguments-input") as HTMLTextAreaElement;
    expect(JSON.parse(input.value)).toEqual({ org: "acme" });
    fireEvent.change(input, { target: { value: '{"org": "acme", "state": "open"}' } });
    expect(seen.table?.arguments).toEqual({ org: "acme", state: "open" });
    fireEvent.change(input, { target: { value: "[1]" } });
    expect(screen.getByText("Give a JSON object of argument names and values")).toBeTruthy();
    expect(seen.table?.arguments).toEqual({ org: "acme", state: "open" });
    fireEvent.change(input, { target: { value: "{" } });
    expect(screen.getByText("Not valid JSON")).toBeTruthy();
    fireEvent.change(input, { target: { value: "" } });
    expect(seen.table?.arguments).toEqual({});
  });
});
