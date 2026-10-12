// Copyright (c) 2026 Kenneth Stott
// Canary: 35536ff8-8f08-4db2-addb-6aba0b25aa55
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1986/REQ-1991: the explorer reads a parameterized table as the JSON:API endpoint takes it —
// its parameters in one `params` object, by parameter name, a numeric parameter as a number. The
// request is not run until every required parameter has a value.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "../test-utils/render";

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ role: { id: "org_admin" }, selectedRoles: [{ id: "org_admin" }] }),
}));

vi.mock("../context/DomainFilterContext", () => ({
  useDomainFilter: () => ({ checkedDomains: new Set<string>() }),
}));

vi.mock("../hooks/useAdminQueries", () => ({
  useDomains: () => ({ domains: [{ id: "sales", description: "Sales" }] }),
  useTables: () => ({
    tables: [
      {
        id: "t1",
        domainId: "sales",
        tableName: "orders",
        columns: [
          { columnName: "id", nativeFilterType: null },
          {
            columnName: "_nf_region",
            nativeFilterType: "query_param",
            nativeFilterRequired: true,
            dataType: "varchar",
          },
          {
            columnName: "_nf_min",
            nativeFilterType: "query_param",
            nativeFilterRequired: false,
            dataType: "double",
          },
        ],
      },
    ],
  }),
  useAllRelationships: () => ({ relationships: [] }),
}));

import { JsonApiPage } from "../pages/JsonApiPage";

function shownParams(container: HTMLElement): string | null {
  const shown = container.querySelector(".jsonapi-url")?.textContent ?? "";
  return new URLSearchParams(shown.includes("?") ? shown.split("?")[1] : "").get("params");
}

describe("JsonApiPage — parameters", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("[]", { status: 200, headers: { "content-type": "application/json" } }),
      ),
    );
  });

  it("sends the parameters by name, and runs only once the required one is given", async () => {
    const { container } = render(<JsonApiPage />, {
      initialEntries: [
        { pathname: "/jsonapi", state: { jsonapiUrl: "/data/jsonapi/sales/orders" } },
      ],
    });
    const region = await screen.findByTestId("jsonapi-param-region");
    expect(screen.getByTestId("jsonapi-param-min")).toBeTruthy();
    expect(screen.getByTestId("jsonapi-run-button")).toHaveProperty("disabled", true);
    expect(shownParams(container)).toBeNull();

    fireEvent.change(region, { target: { value: "EU" } });
    fireEvent.change(screen.getByTestId("jsonapi-param-min"), { target: { value: "100" } });

    await waitFor(() => {
      expect(JSON.parse(shownParams(container) ?? "{}")).toEqual({ region: "EU", min: 100 });
    });
    expect(screen.getByTestId("jsonapi-run-button")).toHaveProperty("disabled", false);
  });
});

describe("JsonApiPage — parameters are not data columns", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("[]", { status: 200, headers: { "content-type": "application/json" } }),
      ),
    );
  });

  it("lists only data columns in Fields", async () => {
    render(<JsonApiPage />, {
      initialEntries: [
        { pathname: "/jsonapi", state: { jsonapiUrl: "/data/jsonapi/sales/orders" } },
      ],
    });
    await screen.findByTestId("jsonapi-param-region");
    fireEvent.click(screen.getByTestId("jsonapi-fields-trigger"));
    await waitFor(() => expect(screen.getAllByText("id").length).toBeGreaterThan(0));
    expect(screen.queryByText("_nf_region")).toBeNull();
    expect(screen.queryByText("_nf_min")).toBeNull();
  });
});
