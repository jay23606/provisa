// Copyright (c) 2026 Kenneth Stott
// Canary: 9e3b7c15-4a62-4d8f-b0c1-5f2a8e6d9b37
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The graph explorer draws the first "max nodes" rows of a result that returns nodes and says so
// over the canvas. Max nodes is the viewer's setting in the side rail, saved per scope, held to the
// server's ceiling (graph-schema's node_cap); every query asks for it. A result that returns rows
// only (no graph columns) is not drawn, whatever its values look like.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import type { FrameData } from "../components/graph/graph-model";
import { getStored, setStored } from "../lib/browserStorage";
import { MAX_NODES_KEY } from "../components/graph/graph-drawing";
import "../i18n";

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    role: { id: "org_admin" },
    selectedRoles: [{ id: "org_admin" }],
    loading: false,
  }),
}));
vi.mock("../context/DomainFilterContext", () => ({
  useDomainFilter: () => ({ checkedDomains: new Set<string>() }),
}));
vi.mock("../hooks/useAdminQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../hooks/useAdminQueries")>()),
  useRelationships: () => ({ relationships: [], refetch: vi.fn() }),
  useAllRelationships: () => ({ relationships: [], refetch: vi.fn() }),
  useUpsertRelationship: () => ({ upsertRelationship: vi.fn() }),
}));
// The canvas, as the frame hands it its note.
vi.mock("../components/graph/GraphCanvas", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../components/graph/GraphCanvas")>()),
  GraphCanvas: ({ note }: { note?: ReactNode }) => <div data-testid="canvas">{note}</div>,
}));
// The page's frames, as it hands them to their component.
const framesSeen: FrameData[] = [];
vi.mock("../components/graph/GraphFrame", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../components/graph/GraphFrame")>();
  return {
    GraphFrame: (props: Parameters<typeof actual.GraphFrame>[0]) => {
      framesSeen.push(props.frame);
      return <actual.GraphFrame {...props} />;
    },
  };
});
vi.mock("../components/graph/Neo4jExportModal", () => ({ Neo4jExportModal: () => null }));

import { GraphPage } from "../pages/GraphPage";

const NODE = (id: number) => ({
  identity: `Customers:${id}`,
  id,
  label: "Customers",
  labels: ["Customers"],
  properties: { id },
});

function Run({ query }: { query: string }) {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate("/graph", { state: { query, autoRun: true } })}>run</button>
  );
}

let cypherBodies: { max_nodes?: number }[] = [];

function serve(answer: Record<string, unknown>) {
  cypherBodies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      let body: unknown = {};
      if (String(url).includes("/data/cypher")) {
        cypherBodies.push(JSON.parse(String(init?.body)));
        body = answer;
      } else if (String(url).includes("/data/graph-schema")) {
        body = { node_cap: 500, node_labels: [], relationship_types: [] };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

function renderPage(query: string) {
  render(
    <MantineProvider>
      <MemoryRouter initialEntries={["/graph"]}>
        <Run query={query} />
        <GraphPage />
      </MemoryRouter>
    </MantineProvider>,
  );
}

async function done(query: string): Promise<FrameData> {
  await waitFor(() =>
    expect(framesSeen.some((f) => f.status === "done" && f.query === query)).toBe(true),
  );
  return framesSeen.filter((f) => f.status === "done" && f.query === query).at(-1)!;
}

describe("GraphPage — max nodes", () => {
  beforeEach(() => {
    localStorage.clear();
    framesSeen.length = 0;
  });

  it("draws the first max-nodes rows of a node result and says so over the canvas", async () => {
    serve({
      type: "cypher",
      columns: ["c"],
      rows: [{ c: NODE(1) }, { c: NODE(2) }],
      graph_columns: { c: "node" },
      truncated: true,
    });
    const query = "MATCH (c:Customers) RETURN c";
    renderPage(query);
    act(() => screen.getByText("run").click());
    const frame = await done(query);
    expect(frame.nodes.size).toBe(2);
    expect(frame.truncated).toBe(true);
    const note = await screen.findByTestId("graph-cut-note");
    expect(note.textContent).toBe(
      "Showing the first 2 nodes; there are more. Raise the limit in the side menu.",
    );
    expect(screen.getByTestId("canvas").contains(note)).toBe(true);
  });

  it("asks for the viewer's setting, saved per scope", async () => {
    setStored(MAX_NODES_KEY, "250");
    serve({ type: "cypher", columns: [], rows: [], graph_columns: {} });
    const query = "MATCH (c:Customers) RETURN c";
    renderPage(query);
    act(() => screen.getByText("run").click());
    await done(query);
    expect(cypherBodies.at(-1)?.max_nodes).toBe(250);
  });

  it("changes the setting from the side rail, held to the server's ceiling", async () => {
    serve({ type: "cypher", columns: [], rows: [], graph_columns: {} });
    renderPage("RETURN 1");
    fireEvent.click(screen.getByTestId("graph-sidebar-tab-settings"));
    // The default, 1,000, is above the ceiling the server said (500): the rail shows the ceiling.
    // The field is drawn again once the ceiling is known (its hint appears), so it is read anew.
    const input = () => screen.getByTestId("graph-max-nodes") as HTMLInputElement;
    await waitFor(() => expect(input().value).toBe("500"));
    expect(screen.getByText("Nodes drawn per query, up to 500")).toBeTruthy();
    fireEvent.change(input(), { target: { value: "120" } });
    await waitFor(() => expect(getStored(MAX_NODES_KEY)).toBe("120"));
    act(() => screen.getByText("run").click());
    await waitFor(() => expect(cypherBodies.at(-1)?.max_nodes).toBe(120));
  });

  it("draws nothing of a rows-only result, however its values look", async () => {
    serve({
      type: "cypher",
      columns: ["c"],
      rows: [{ c: NODE(1) }],
      graph_columns: {},
    });
    const query = "MATCH (c:Customers) RETURN c {.*} AS c";
    renderPage(query);
    act(() => screen.getByText("run").click());
    const frame = await done(query);
    expect(frame.nodes.size).toBe(0);
    expect(frame.truncated).toBe(false);
  });
});
