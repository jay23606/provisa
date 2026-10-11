// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The Roles and RLS pages show a row's detail in the right-hand panel, not under the row: one at
// a time, the row marked, another row swapping it; the "+" opener's form opens in the same panel
// under its own title; Escape never drops a form that is being typed into.

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "../../test-utils/render";

const role = (id: string, detailsHidden = false) => ({
  id,
  capabilities: [],
  demonstrated: [],
  domain_access: ["sales"],
  parentRoleId: null,
  detailsHidden,
});
const ROLES = [role("analyst"), role("steward"), role("locked", true)];
const RULES = [
  { id: 1, tableId: null, domainId: "sales", actionName: null, roleId: "analyst", filterExpr: "a" },
  { id: 2, tableId: null, domainId: "sales", actionName: null, roleId: "steward", filterExpr: "b" },
];

vi.mock("../../context/DomainFilterContext", () => ({
  useDomainFilter: () => ({
    domains: [],
    setDomains: vi.fn(),
    setSelectedDomain: vi.fn(),
    checkedDomains: new Set<string>(),
  }),
}));
vi.mock("../../hooks/useAdminQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../hooks/useAdminQueries")>()),
  useRoles: () => ({ roles: ROLES, loading: false, refetch: vi.fn() }),
  useTables: () => ({ tables: [], loading: false, refetch: vi.fn() }),
  useDomains: () => ({ domains: [{ id: "sales" }], loading: false, refetch: vi.fn() }),
}));
vi.mock("../../hooks/useSecurityQueries", () => ({
  useRLSRules: () => ({ rlsRules: RULES, loading: false, refetch: vi.fn() }),
  useUpsertRole: () => ({ upsertRole: vi.fn(), loading: false }),
  useDeleteRole: () => ({ deleteRole: vi.fn(), loading: false }),
  useUpsertRlsRule: () => ({ upsertRlsRule: vi.fn(), loading: false }),
  useDeleteRlsRule: () => ({ deleteRlsRule: vi.fn(), loading: false }),
  useRevokeRoleGrants: () => ({ revokeFromTable: vi.fn(), revokeFromObject: vi.fn() }),
}));
vi.mock("../../api/actions", () => ({
  fetchActions: vi.fn().mockResolvedValue({ functions: [], webhooks: [] }),
}));

import { SecurityRolesPage } from "../SecurityPage";
import { SecurityRlsPage } from "../security/SecurityRlsPage";

const rowIn = (list: string, text: string) =>
  within(screen.getByTestId(list)).getByText(text).closest("tr")!;

describe("SecurityRolesPage: the right-hand detail panel", () => {
  it("shows the chosen role in the panel, marks its row, swaps and closes", () => {
    render(<SecurityRolesPage />);
    expect(screen.queryByTestId("roles-split-panel")).toBeNull();

    fireEvent.click(rowIn("roles-list", "analyst"));
    expect(screen.getByTestId("roles-split-title")).toHaveTextContent("analyst");
    expect(rowIn("roles-list", "analyst").className).toContain("row-selected");
    expect(within(screen.getByTestId("roles-split-panel")).getByTestId("edit-role-analyst")).toBe(
      screen.getByTestId("edit-role-analyst"),
    );

    fireEvent.click(rowIn("roles-list", "steward"));
    expect(screen.getByTestId("roles-split-title")).toHaveTextContent("steward");
    expect(rowIn("roles-list", "analyst").className).not.toContain("row-selected");

    fireEvent.click(screen.getByTestId("roles-split-close"));
    expect(screen.queryByTestId("roles-split-panel")).toBeNull();
  });

  it("opens no panel for a role whose details are hidden", () => {
    render(<SecurityRolesPage />);
    fireEvent.click(rowIn("roles-list", "locked"));
    expect(screen.queryByTestId("roles-split-panel")).toBeNull();
    expect(rowIn("roles-list", "locked").className).not.toContain("row-selected");
  });

  it("opens the new-role form in the panel, in place of the open role", () => {
    render(<SecurityRolesPage />);
    fireEvent.click(rowIn("roles-list", "analyst"));
    fireEvent.click(screen.getByTestId("toggle-role-form"));
    expect(screen.getByTestId("roles-split-title")).toHaveTextContent("New role");
    expect(
      within(screen.getByTestId("roles-split-panel")).getByTestId("role-id-input"),
    ).toBeTruthy();
    expect(rowIn("roles-list", "analyst").className).not.toContain("row-selected");
  });

  it("keeps Escape from dropping the form of a role being edited", () => {
    render(<SecurityRolesPage />);
    fireEvent.click(rowIn("roles-list", "analyst"));
    fireEvent.click(screen.getByTestId("edit-role-analyst"));
    fireEvent.keyDown(screen.getByTestId("roles-split-panel"), { key: "Escape" });
    expect(screen.getByTestId("save-role-analyst")).toBeTruthy();
  });
});

describe("SecurityRlsPage: the right-hand detail panel", () => {
  it("shows the chosen rule in the panel, marks its row, and swaps", () => {
    render(<SecurityRlsPage />);
    expect(screen.queryByTestId("rules-split-panel")).toBeNull();

    fireEvent.click(rowIn("rules-list", "analyst"));
    expect(screen.getByTestId("rules-split-title")).toHaveTextContent("RLS rule 1");
    expect(rowIn("rules-list", "analyst").className).toContain("row-selected");
    expect(within(screen.getByTestId("rules-split-panel")).getByTestId("edit-rule-1")).toBeTruthy();

    fireEvent.click(rowIn("rules-list", "steward"));
    expect(screen.getByTestId("rules-split-title")).toHaveTextContent("RLS rule 2");
  });

  it("opens the new-rule form in the panel, and Escape leaves it open", () => {
    render(<SecurityRlsPage />);
    fireEvent.click(screen.getByTestId("toggle-rule-form"));
    expect(screen.getByTestId("rules-split-title")).toHaveTextContent("New RLS rule");
    const panel = screen.getByTestId("rules-split-panel");
    expect(within(panel).getByTestId("save-rule")).toBeTruthy();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.getByTestId("save-rule")).toBeTruthy();
  });
});
