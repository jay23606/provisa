// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// An RLS rule's panel shows every value of the rule under its form's labels: what it applies to
// and that one's domain, the table or action it names, the role and the filter.

import { describe, it, expect } from "vitest";
import { render, screen, within } from "../../../test-utils/render";
import type { RLSRule } from "../../../types/admin";
import { RlsRuleRead } from "../RlsRuleRead";

const rule = (over: Partial<RLSRule>): RLSRule => ({
  id: 3,
  tableId: 7,
  domainId: null,
  actionName: null,
  roleId: "analyst",
  filterExpr: "region = 'east'",
  ...over,
});

function fields(id: number): [string, string][] {
  return within(screen.getByTestId(`rule-read-${id}`))
    .queryAllByRole("term")
    .map((dt) => [dt.textContent ?? "", dt.nextElementSibling?.textContent ?? ""]);
}

describe("an RLS rule's read view", () => {
  it("shows a table rule's every value, its table's domain among them", () => {
    render(<RlsRuleRead rule={rule({})} domain="sales" tableLabel="sales.orders" />);
    expect(fields(3)).toEqual([
      ["Rule ID", "3"],
      ["Apply To", "Specific Table"],
      ["Domain", "sales"],
      ["Table", "sales.orders"],
      ["Role", "analyst"],
      ["Filter Expression", "region = 'east'"],
    ]);
  });

  it("shows a domain rule with its domain, and an action rule with its action", () => {
    const { unmount } = render(
      <RlsRuleRead
        rule={rule({ tableId: null, domainId: "ops" })}
        domain="ops"
        tableLabel={null}
      />,
    );
    expect(fields(3)).toEqual([
      ["Rule ID", "3"],
      ["Apply To", "Entire Domain"],
      ["Domain", "ops"],
      ["Role", "analyst"],
      ["Filter Expression", "region = 'east'"],
    ]);
    unmount();
    render(
      <RlsRuleRead
        rule={rule({ id: 9, tableId: null, actionName: "notify_ops" })}
        domain={null}
        tableLabel={null}
      />,
    );
    // An action registered in no domain: its domain is shown empty, not left out.
    expect(fields(9)).toEqual([
      ["Rule ID", "9"],
      ["Apply To", "Action (function or webhook)"],
      ["Domain", "—"],
      ["Action", "notify_ops"],
      ["Role", "analyst"],
      ["Filter Expression", "region = 'east'"],
    ]);
  });
});
