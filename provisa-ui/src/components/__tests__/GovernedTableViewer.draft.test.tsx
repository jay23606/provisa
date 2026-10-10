// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1921: a draft's Preview is the full viewer. A draft is read by no statement a caller sends,
// so every page, filter and sort of it goes to the admin preview as the viewer's choices -- the
// server writes the statement -- and never to /data/sql.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "../../test-utils/render";
import type { RegisteredTable } from "../../types/admin";
import { previewTable, runSql } from "../../api/admin";
import { viewerRequest } from "../nativeParams";
import type { ActiveFilter } from "../../pages/sql/columnFilter";

vi.mock("../../api/admin", () => ({ runSql: vi.fn(), previewTable: vi.fn() }));

import { GovernedTableViewer } from "../GovernedTableViewer";
import { TablePreviewModal } from "../TablePreviewModal";

const DRAFT = {
  id: 9,
  sourceId: "pg",
  domainId: "sales",
  schemaName: "public",
  tableName: "refunds",
  alias: null,
  description: null,
  apiEndpoint: null,
  viewSql: null,
  draft: true,
  columns: [],
} as unknown as RegisteredTable;

function page(from: number, count: number) {
  const rows = Array.from({ length: count }, (_, i) => ({ id: from + i, note: `n${from + i}` }));
  return { columns: ["id", "note"], rows, rowCount: rows.length, draft: true };
}

const requests = () => vi.mocked(previewTable).mock.calls.map((call) => call[2]);

describe("GovernedTableViewer over a draft", () => {
  beforeEach(() => {
    vi.mocked(runSql).mockReset();
    vi.mocked(previewTable).mockReset();
    localStorage.clear();
  });

  it("reads its first page through the admin preview, as the role it was given", async () => {
    vi.mocked(previewTable).mockResolvedValue(page(0, 3));
    render(<GovernedTableViewer table={DRAFT} role="steward" />);
    expect(await screen.findByText("n2")).toBeInTheDocument();
    const [tableId, role, request] = vi.mocked(previewTable).mock.calls[0];
    expect([tableId, role]).toEqual([9, "steward"]);
    expect(request).toMatchObject({ filters: [], sorts: [], groupBy: [], page: 0 });
    expect(runSql).not.toHaveBeenCalled();
  });

  it("filters, sorts and pages through the admin preview and never sends a statement", async () => {
    // A full page plus the probe row, so the grid offers a next page.
    vi.mocked(previewTable).mockImplementation(async (_id, _role, request) =>
      page(request.page * request.pageSize, request.pageSize + 1),
    );
    render(<GovernedTableViewer table={DRAFT} role="steward" />);
    await screen.findByText("n0");

    fireEvent.change(screen.getByLabelText("Filter rows… note"), { target: { value: "late" } });
    await waitFor(() =>
      expect(requests().at(-1)?.filters).toEqual([
        { col: "note", kind: "text", op: "contains", a: "late" },
      ]),
    );

    fireEvent.click(screen.getByText("id", { selector: ".th-label span" }));
    await waitFor(() => expect(requests().at(-1)?.sorts).toEqual([{ col: "id", dir: "asc" }]));
    expect(requests().at(-1)?.filters).toHaveLength(1); // the filter is still part of the choice

    fireEvent.click(screen.getByLabelText("Next page"));
    await waitFor(() => expect(requests().at(-1)?.page).toBe(1));

    expect(runSql).not.toHaveBeenCalled();
  });

  it("shows the server's refusal where the rows would be", async () => {
    vi.mocked(previewTable).mockRejectedValue(new Error("No access to domain 'sales'"));
    render(<GovernedTableViewer table={DRAFT} role="analyst" />);
    expect(await screen.findByText(/No access to domain 'sales'/)).toBeInTheDocument();
    expect(runSql).not.toHaveBeenCalled();
  });

  it("a table in service is still read by the statement the viewer writes", async () => {
    vi.mocked(runSql).mockResolvedValue({ columns: ["id"], rows: [{ id: 1 }] });
    render(<GovernedTableViewer table={{ ...DRAFT, draft: false }} role="steward" />);
    await waitFor(() => expect(runSql).toHaveBeenCalled());
    expect(previewTable).not.toHaveBeenCalled();
  });
});

describe("TablePreviewModal for a draft", () => {
  beforeEach(() => {
    vi.mocked(runSql).mockReset();
    vi.mocked(previewTable).mockReset();
  });

  it("mounts the same viewer under the line that says whom the table is not yet shown to", async () => {
    vi.mocked(previewTable).mockResolvedValue(page(0, 2));
    render(<TablePreviewModal table={DRAFT} role="steward" onClose={vi.fn()} />);
    expect(await screen.findByTestId("table-preview-draft-note")).toHaveTextContent(
      "Draft preview: readers cannot see this table yet.",
    );
    expect(await screen.findByText("n1")).toBeInTheDocument();
    expect(screen.getByTestId("download-xlsx-btn")).toBeInTheDocument(); // the full viewer
    expect(runSql).not.toHaveBeenCalled();
  });

  it("says nothing of drafts over a table in service", async () => {
    vi.mocked(runSql).mockResolvedValue({ columns: ["id"], rows: [{ id: 1 }] });
    render(
      <TablePreviewModal table={{ ...DRAFT, draft: false }} role="steward" onClose={vi.fn()} />,
    );
    await waitFor(() => expect(runSql).toHaveBeenCalled());
    expect(screen.queryByTestId("table-preview-draft-note")).not.toBeInTheDocument();
  });
});

describe("viewerRequest", () => {
  const filter = (col: string, kind: ActiveFilter["kind"], spec: ActiveFilter["spec"]) => ({
    col,
    kind,
    spec,
  });

  it("carries each usable filter as it is held, and a date filter's bounds resolved here", () => {
    const now = new Date(2026, 9, 10, 15, 30, 0);
    const request = viewerRequest(
      DRAFT,
      {},
      [
        filter("note", "text", { op: "contains", a: "Late" }),
        filter("id", "number", { op: "between", a: "9", b: "2" }),
        filter("at", "date", { op: "today" }),
        filter("note", "text", { op: "in", a: "ci", values: ["A"] }),
        filter("id", "number", { op: "eq", a: "" }), // not usable yet: narrows nothing
      ],
      [{ col: "id", dir: "desc" }],
      ["note"],
      2,
      50,
      now,
    );
    expect(request).toEqual({
      params: [],
      filters: [
        { col: "note", kind: "text", op: "contains", a: "Late" },
        { col: "id", kind: "number", op: "between", a: "9", b: "2" },
        {
          col: "at",
          kind: "date",
          op: "today",
          from: "2026-10-10 00:00:00",
          to: "2026-10-11 00:00:00",
        },
        { col: "note", kind: "text", op: "in", a: "ci", values: ["A"] },
      ],
      sorts: [{ col: "id", dir: "desc" }],
      groupBy: ["note"],
      page: 2,
      pageSize: 50,
    });
  });
});
