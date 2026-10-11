// Copyright (c) 2026 Kenneth Stott
// Canary: dbd65602-0cb3-4465-a0c1-d0bd62891a4a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The Relationships page shows a relationship in the right-hand panel, not under its row: one at a
// time, the row marked, another row swapping it; the forms that add a relationship and that create
// a relationship's reverse open in the same panel, the reverse with a way back.

import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent, within } from "@testing-library/react";
import { render } from "../../test-utils/render";
import { RelationshipsPage } from "../RelationshipsPage";

const rel = (id: string, source: string, column: string, target: string) => ({
  id,
  sourceTableId: 1,
  targetTableId: 2,
  sourceTableName: source,
  sourceDomainId: "sales",
  targetTableName: target,
  sourceColumn: column,
  targetColumn: "id",
  cardinality: "many-to-one",
  materialize: false,
  refreshInterval: 300,
  targetFunctionName: null,
  functionArg: null,
  alias: null,
  graphqlAlias: null,
  computedCypherAlias: null,
  autoSuggested: false,
  disableCypher: false,
  viaTableName: null,
});

// Stable objects: a hook that answered a new array each render would re-run the page's effects.
const RELS = {
  relationships: [
    rel("orders-to-customers", "orders", "customer_id", "customers"),
    rel("orders-to-regions", "orders", "region_id", "regions"),
  ],
  loading: false,
  refetch: vi.fn(),
};
const TABLES = { tables: [], loading: false };
const DOMAINS = { domains: [] };
const UPSERT = { upsertRelationship: vi.fn(async () => ({ success: true, message: "" })) };
const DELETE = { deleteRelationship: vi.fn() };
const AUTH = { capabilities: ["create_relationship"] };
const FILTER = { domainsEnabled: false, domains: [], checkedDomains: new Set<string>() };

vi.mock("../../hooks/useAdminQueries", () => ({
  useRelationships: () => RELS,
  useAllRelationships: () => RELS,
  useTables: () => TABLES,
  useDomains: () => DOMAINS,
  useUpsertRelationship: () => UPSERT,
  useDeleteRelationship: () => DELETE,
}));
vi.mock("../../context/AuthContext", () => ({ useAuth: () => AUTH }));
vi.mock("../../context/DomainFilterContext", () => ({ useDomainFilter: () => FILTER }));
vi.mock("../../api/admin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/admin")>()),
  fetchCandidates: vi.fn().mockResolvedValue([]),
  fetchRejectedCount: vi.fn().mockResolvedValue(0),
}));
vi.mock("../../api/actions", () => ({
  fetchActions: vi.fn().mockResolvedValue({ functions: [], webhooks: [] }),
}));
vi.mock("../../components/TagControl", () => ({ TagControl: () => null }));

// The detail names the same columns, so a row is looked for in the list.
const rowOf = (text: string) =>
  within(screen.getByTestId("relationships-list")).getByText(text).closest("tr")!;
const panel = () => screen.getByTestId("relationships-split-panel");

describe("RelationshipsPage: the right-hand detail panel", () => {
  it("has no panel until a row is chosen, then shows that relationship and marks its row", () => {
    render(<RelationshipsPage />);
    expect(screen.queryByTestId("relationships-split-panel")).toBeNull();

    fireEvent.click(rowOf("orders.customer_id"));
    expect(screen.getByTestId("relationships-split-title")).toHaveTextContent(
      "orders-to-customers",
    );
    expect(rowOf("orders.customer_id").className).toContain("row-selected");
    // Its actions are in the panel, not under the row.
    expect(within(panel()).getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("swaps to another row, and closes from the row or the panel's close", () => {
    render(<RelationshipsPage />);
    fireEvent.click(rowOf("orders.customer_id"));
    fireEvent.click(rowOf("orders.region_id"));
    expect(screen.getByTestId("relationships-split-title")).toHaveTextContent("orders-to-regions");
    expect(rowOf("orders.customer_id").className).not.toContain("row-selected");

    fireEvent.click(rowOf("orders.region_id"));
    expect(screen.queryByTestId("relationships-split-panel")).toBeNull();

    fireEvent.click(rowOf("orders.region_id"));
    fireEvent.click(screen.getByTestId("relationships-split-close"));
    expect(screen.queryByTestId("relationships-split-panel")).toBeNull();
  });

  it("opens the add form in the panel, titled, in place of the open relationship", () => {
    render(<RelationshipsPage />);
    fireEvent.click(rowOf("orders.customer_id"));
    fireEvent.click(screen.getByTestId("rels-add-toggle"));
    expect(screen.getByTestId("relationships-split-title")).toHaveTextContent("New relationship");
    expect(within(panel()).getByTestId("add-relationship-form")).toBeTruthy();
    expect(rowOf("orders.customer_id").className).not.toContain("row-selected");
  });

  it("asks a new relationship only for what it needs to exist", () => {
    render(<RelationshipsPage />);
    fireEvent.click(screen.getByTestId("rels-add-toggle"));
    const form = within(screen.getByTestId("add-relationship-form"));
    expect(form.getByTestId("rel-form-id")).toBeTruthy();
    expect(form.getByText("Source Table")).toBeTruthy();
    expect(form.getByText("Cardinality")).toBeTruthy();
    // The rest is edited in the detail the save opens.
    expect(form.queryByTestId("rel-form-alias")).toBeNull();
    expect(form.queryByTestId("rel-form-graphql-alias")).toBeNull();
    expect(form.queryByTestId("rel-form-refresh-interval")).toBeNull();
    expect(form.queryByText(/Materialize/)).toBeNull();
    expect(form.queryByText(/Junction table/)).toBeNull();
  });

  it("opens the reverse form in the panel, with a way back to the relationship", () => {
    render(<RelationshipsPage />);
    fireEvent.click(rowOf("orders.customer_id"));
    fireEvent.click(within(panel()).getByRole("button", { name: "Generate reverse relationship" }));
    expect(within(panel()).getByTestId("reverse-relationship-form")).toBeTruthy();
    expect(screen.getByTestId("reverse-rel-id")).toHaveValue("customers-to-orders");

    fireEvent.click(screen.getByTestId("reverse-rel-back"));
    expect(screen.queryByTestId("reverse-relationship-form")).toBeNull();
    expect(screen.getByTestId("relationships-split-title")).toHaveTextContent(
      "orders-to-customers",
    );
  });

  it("keeps Escape from dropping a form that is being typed into", () => {
    render(<RelationshipsPage />);
    fireEvent.click(rowOf("orders.customer_id"));
    fireEvent.click(within(panel()).getByRole("button", { name: "Edit" }));
    fireEvent.keyDown(panel(), { key: "Escape" });
    expect(screen.getByTestId("relationships-split-panel")).toBeTruthy();

    fireEvent.click(within(panel()).getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(panel(), { key: "Escape" });
    expect(screen.queryByTestId("relationships-split-panel")).toBeNull();
  });
});
