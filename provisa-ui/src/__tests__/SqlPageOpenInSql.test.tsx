// Copyright (c) 2026 Kenneth Stott
// Canary: dd10736c-f7d3-4d00-ace2-9840a9d1ecc1
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// "Open in SQL" (the GraphQL page's tools, NL, Polly) navigates to /sql with the statement as router
// state. The new tab's editor shows that statement, not the query of the tab that was active.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { useNavigate } from "react-router-dom";
import { renderWithProviders } from "../test-utils/render";

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ role: { id: "org_admin" }, selectedRoles: [{ id: "org_admin" }] }),
}));
vi.mock("../context/DomainFilterContext", () => ({
  useDomainFilter: () => ({ checkedDomains: new Set<string>(), ensureDomainChecked: vi.fn() }),
}));
vi.mock("../hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("../hooks/useAdminQueries", () => ({
  useRoles: () => ({ roles: [{ id: "org_admin" }] }),
  useDomains: () => ({ domains: [] }),
  useTables: () => ({ tables: [], refetch: vi.fn() }),
  useRelationships: () => ({ relationships: [], refetch: vi.fn() }),
  useMetrics: () => ({ metrics: [] }),
  useRegisterTable: () => ({ registerTable: vi.fn() }),
  useUpdateTable: () => ({ updateTable: vi.fn() }),
}));

import { SqlPage } from "../pages/SqlPage";
import { persistTabsMeta, emptyTab } from "../pages/sql/tabHelpers";

// CodeMirror measures text with Range.getClientRects, which jsdom does not implement.
Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
Range.prototype.getBoundingClientRect = () => new DOMRect();

const OLD = "SELECT 1 AS previous_tab";
const HANDED = "SELECT 42 AS from_graphql";

/** What the SQL editor shows. */
function editorText(): string {
  return (document.querySelector(".cm-content")?.textContent ?? "").replace(/\s+/g, " ");
}

function OpenInSql() {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate("/sql", { state: { sql: HANDED, autoRun: true } })}>
      open-in-sql
    </button>
  );
}

describe("SqlPage — Open in SQL", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ columns: [], rows: [] }), { status: 200 })),
    );
  });

  it("shows the handed statement in the new tab of a page opened by the hand-off", async () => {
    persistTabsMeta([emptyTab("t-old", "Query 1", OLD)], "t-old");
    renderWithProviders(<SqlPage />, {
      initialEntries: [{ pathname: "/sql", state: { sql: HANDED, autoRun: true } }],
    });
    await waitFor(() => expect(screen.getAllByText(/Query 2/).length).toBeGreaterThan(0));
    await waitFor(() => expect(editorText()).toBe(HANDED));
    // And it stays: nothing writes the previous tab's query back.
    await new Promise((r) => setTimeout(r, 300));
    expect(editorText()).toBe(HANDED);
    // What ran is the handed statement, never the previous tab's.
    const ran = vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes("/data/sql"))
      .map(([, init]) => String((init as RequestInit | undefined)?.body ?? ""));
    expect(ran.some((body) => body.includes("from_graphql"))).toBe(true);
    expect(ran.some((body) => body.includes("previous_tab"))).toBe(false);
  });

  it("shows the handed statement in the new tab of a page already open", async () => {
    persistTabsMeta([emptyTab("t-old", "Query 1", OLD)], "t-old");
    renderWithProviders(
      <>
        <OpenInSql />
        <SqlPage />
      </>,
      { initialEntries: ["/sql"] },
    );
    await waitFor(() => expect(editorText()).toBe(OLD));
    act(() => screen.getByText("open-in-sql").click());
    await waitFor(() => expect(screen.getAllByText(/Query 2/).length).toBeGreaterThan(0));
    await waitFor(() => expect(editorText()).toBe(HANDED));
    await new Promise((r) => setTimeout(r, 300));
    expect(editorText()).toBe(HANDED);
  });
});
