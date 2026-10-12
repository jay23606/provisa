// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1954: a ServiceNow table is offered an import set only when the instance has an active
// transform map into it; unbound is the default, and a map is the steward's choice.

import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing/react";
import { fireEvent } from "@testing-library/react";
import { renderInForm, screen } from "../../../test-utils/render";
import { AvailableImportSets } from "../../../hooks/admin.graphql";
import { ImportSetField } from "../ImportSetField";

const asked = (tableName: string) => ({
  query: AvailableImportSets,
  variables: { sourceId: "helpdesk", schemaName: "helpdesk", tableName },
});

function show(tableName: string, maps: { name: string; importSet: string }[], value = null) {
  const onChange = vi.fn();
  const mocks = [
    {
      request: asked(tableName),
      result: {
        data: {
          availableImportSets: maps.map((m) => ({ __typename: "ImportSetType", ...m })),
        },
      },
    },
  ];
  renderInForm(
    <MockedProvider mocks={mocks}>
      <ImportSetField
        sourceId="helpdesk"
        schemaName="helpdesk"
        tableName={tableName}
        value={value}
        onChange={onChange}
      />
    </MockedProvider>,
  );
  return onChange;
}

describe("ImportSetField", () => {
  it("offers each transform map into the table, unbound by default", async () => {
    const onChange = show("sys_user", [
      { name: "User Import", importSet: "imp_user" },
      { name: "LDAP User Import", importSet: "ldap_import" },
    ]);
    const select = await screen.findByTestId("register-table-import-set");
    expect(select).toHaveValue("None: write inserts to the table directly");
    fireEvent.click(select);
    const options = await screen.findAllByRole("option", { hidden: true });
    expect(options.map((o) => o.textContent)).toEqual([
      "None: write inserts to the table directly",
      "User Import (imp_user)",
      "LDAP User Import (ldap_import)",
    ]);
    fireEvent.click(
      screen.getByRole("option", { name: "LDAP User Import (ldap_import)", hidden: true }),
    );
    expect(onChange).toHaveBeenLastCalledWith("ldap_import");
  });

  it("offers nothing for a table no transform map writes into", async () => {
    show("incident", []);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("register-table-import-set")).toBeNull();
  });
});
