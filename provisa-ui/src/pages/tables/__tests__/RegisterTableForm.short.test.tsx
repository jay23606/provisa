// Copyright (c) 2026 Kenneth Stott
// Canary: 956da361-be4f-4b70-8320-c8e665bcd0de
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The short register step: what names the table, and only what the server will not do without.
// The rest is the editor's, which opens on the draft once it is registered.

import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "../../../test-utils/render";

vi.mock("../../../context/DomainFilterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../context/DomainFilterContext")>()),
  useDomainFilter: () => ({ ensureDomainChecked: vi.fn() }),
}));

vi.mock("../../../hooks/useAdminQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../hooks/useAdminQueries")>()),
  useAvailableSchemas: () => ({ schemas: ["openapi"], loading: false }),
  useAvailableTables: () => ({
    tables: [{ name: "getStore", comment: "The store", pagingKind: null, pagination: null }],
    loading: false,
  }),
}));

const { RegisterTableForm } = await import("../RegisterTableForm");

function renderForm(domainHints: string[]) {
  const registerTable = vi.fn().mockResolvedValue({ success: true, message: "" });
  const onSuccess = vi.fn();
  render(
    <RegisterTableForm
      sources={[{ id: "petstore", type: "openapi", allowedDomains: [] } as never]}
      domainHints={domainHints}
      domainAccess={["*"]}
      checkedDomains={new Set<string>()}
      domainsEnabled={true}
      tables={[]}
      roles={[{ id: "admin" } as never]}
      getAvailableColumnsMetadata={vi.fn().mockResolvedValue([
        { name: "id", dataType: "integer", isPrimaryKey: true },
        { name: "name", dataType: "varchar" },
      ])}
      suggestTableAlias={vi.fn().mockResolvedValue("")}
      registerTable={registerTable}
      onSuccess={onSuccess}
      onCancel={() => {}}
      setError={vi.fn()}
    />,
  );
  return { registerTable, onSuccess };
}

async function pick(domain?: string) {
  const user = userEvent.setup();
  await user.selectOptions(screen.getByTestId("register-table-source-select"), "petstore");
  if (domain) await user.selectOptions(screen.getByTestId("register-table-domain-select"), domain);
  await user.selectOptions(await screen.findByTestId("register-table-table-select"), "getStore");
  await screen.findByTestId("register-table-columns-summary");
  return user;
}

describe("RegisterTableForm — the short step", () => {
  it("asks only what names the table, none of what the editor holds", async () => {
    renderForm(["sales"]);
    await pick();
    expect(screen.getByTestId("register-table-alias")).toBeInTheDocument();
    for (const absent of [
      "register-table-domain-select",
      "register-table-region-select",
      "register-table-watermark-select",
      "register-table-col-selected-id",
      "uniques-panel",
      "discover-columns-checkbox",
    ])
      expect(screen.queryByTestId(absent)).toBeNull();
    expect(screen.queryByPlaceholderText(/appears in sdl docs/i)).toBeNull();
  });

  it("asks the domain when there is more than one to choose from", async () => {
    const { registerTable } = renderForm(["sales", "finance"]);
    const user = await pick("finance");
    await user.click(screen.getByTestId("register-table-submit"));
    await waitFor(() => expect(registerTable).toHaveBeenCalled());
    expect(registerTable.mock.calls[0][0].domainId).toBe("finance");
  });

  it("registers every discovered column with its type, into the one domain, and names the table", async () => {
    const { registerTable, onSuccess } = renderForm(["sales"]);
    const user = await pick();
    await user.click(screen.getByTestId("register-table-submit"));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const input = registerTable.mock.calls[0][0];
    expect(input.domainId).toBe("sales");
    expect(input.description).toBe("The store");
    expect(
      input.columns.map((c: { name: string; dataType: string }) => [c.name, c.dataType]),
    ).toEqual([
      ["id", "integer"],
      ["name", "varchar"],
    ]);
    expect(onSuccess).toHaveBeenCalledWith({
      sourceId: "petstore",
      schemaName: "openapi",
      tableName: "getStore",
    });
  });
});
