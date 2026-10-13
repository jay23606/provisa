// Copyright (c) 2026 Kenneth Stott
// Canary: b1f4d2a7-9c3e-4a51-8d0b-7e2f6a1c4d90
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "../test-utils/render";
import i18n from "../i18n";
import { ScheduledTasks } from "../components/admin/ScheduledTasks";

const t = i18n.getFixedT("en");

const createSpy = vi.fn(async () => ({ success: true, message: "ok" }));
const deleteSpy = vi.fn(async () => ({ success: true, message: "ok" }));
const toggleSpy = vi.fn(async () => ({ success: true, message: "ok" }));

let mockTasks: unknown[] = [];

// Spread the real module: vmThreads + fileParallelism:false share one module registry, so a
// replace-everything factory here leaks into other files. In particular a stubbed
// useMaterializeStoreInfo would win over the real Apollo hook that
// TableEditForm.consistency drives through MockedProvider.
vi.mock("../hooks/useAdminOpsQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../hooks/useAdminOpsQueries")>()),
  useScheduledTasks: () => ({ scheduledTasks: mockTasks, loading: false }),
  useToggleScheduledTask: () => ({ toggleScheduledTask: toggleSpy }),
  useCreateScheduledTask: () => ({ createScheduledTask: createSpy }),
  useDeleteScheduledTask: () => ({ deleteScheduledTask: deleteSpy }),
}));

vi.mock("../hooks/useAdminQueries", () => ({
  useRoles: () => ({ roles: [{ id: "ops" }, { id: "analyst" }], loading: false }),
}));

vi.mock("../api/actions", () => ({
  fetchActions: vi.fn(async () => ({ functions: [], webhooks: [] })),
}));

describe("ScheduledTasks — SQL trigger", () => {
  beforeEach(() => {
    createSpy.mockClear();
    deleteSpy.mockClear();
    toggleSpy.mockClear();
    mockTasks = [];
  });

  const selectKind = async (label: string) => {
    fireEvent.click(screen.getByRole("textbox", { name: t("scheduledTasks.kindLabel") }));
    const listbox = await screen.findByRole("listbox");
    fireEvent.click(within(listbox).getByText(label));
  };

  it("shows the SQL statement field only when kind is SQL", async () => {
    render(<ScheduledTasks />);
    fireEvent.click(screen.getByTestId("scheduled-tasks-toggle-form"));

    // Webhook kind by default: no SQL field.
    expect(screen.queryByLabelText(t("scheduledTasks.sqlLabel"))).toBeNull();

    await selectKind(t("scheduledTasks.kindSql"));
    expect(await screen.findByLabelText(t("scheduledTasks.sqlLabel"))).toBeTruthy();
    // Date-token hint is visible.
    expect(screen.getByText(/\{\{YYYY-MM-DD\}\}/)).toBeTruthy();
  });

  it("creates a SQL trigger with the entered statement + cron", async () => {
    render(<ScheduledTasks />);
    fireEvent.click(screen.getByTestId("scheduled-tasks-toggle-form"));
    await selectKind(t("scheduledTasks.kindSql"));
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.idLabel")), {
      target: { value: "nightly" },
    });
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.nameLabel")), {
      target: { value: "Nightly Rollup" },
    });
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.cronLabel")), {
      target: { value: "0 2 * * *" },
    });
    fireEvent.change(await screen.findByLabelText(t("scheduledTasks.sqlLabel")), {
      target: { value: "INSERT INTO audit.d SELECT '{{YYYY-MM-DD}}'" },
    });

    // A SQL task runs as a role: without one it is not sent.
    fireEvent.click(screen.getByTestId("scheduled-tasks-submit"));
    expect(await screen.findByText(t("scheduledTasks.validationRoleRequired"))).toBeTruthy();
    expect(createSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("textbox", { name: t("scheduledTasks.roleLabel") }));
    fireEvent.click(await screen.findByRole("option", { name: "ops", hidden: true }));
    fireEvent.click(screen.getByTestId("scheduled-tasks-submit"));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy).toHaveBeenCalledWith({
      id: "nightly",
      name: "Nightly Rollup",
      cron: "0 2 * * *",
      kind: "sql",
      sql: "INSERT INTO audit.d SELECT '{{YYYY-MM-DD}}'",
      role: "ops",
    });
  });

  it("lists an existing SQL trigger and can delete it", async () => {
    mockTasks = [
      {
        id: "nightly",
        name: "Nightly Rollup",
        cronExpression: "0 2 * * *",
        webhookUrl: null,
        kind: "sql",
        sql: "INSERT INTO audit.d SELECT 1",
        role: "ops",
        enabled: true,
        lastRunAt: null,
        nextRunAt: null,
      },
    ];
    render(<ScheduledTasks />);
    expect(screen.getByText("INSERT INTO audit.d SELECT 1")).toBeTruthy();
    expect(screen.getByText(t("scheduledTasks.runsAs", { role: "ops" }))).toBeTruthy();

    // The Delete button asks first, naming the task; nothing is deleted until it is confirmed.
    fireEvent.click(screen.getByRole("button", { name: t("scheduledTasks.delete") }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      t("scheduledTasks.deleteTitle", { name: "Nightly Rollup" }),
    );
    expect(deleteSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith("nightly"));
  });
});

// A mutation wrapper throws when the server answers with GraphQL errors: the action's busy state
// ends, and what went wrong is said, never a button left spinning.
describe("ScheduledTasks — a failed action", () => {
  const TASK = {
    id: "nightly",
    name: "Nightly Rollup",
    cronExpression: "0 2 * * *",
    webhookUrl: null,
    kind: "sql",
    sql: "SELECT 1",
    role: "ops",
    enabled: true,
    lastRunAt: null,
    nextRunAt: null,
  };
  beforeEach(() => {
    mockTasks = [TASK];
  });

  const confirmDelete = async () => {
    fireEvent.click(screen.getByRole("button", { name: t("scheduledTasks.delete") }));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
  };

  it("says why a delete raised, and frees its button", async () => {
    deleteSpy.mockImplementationOnce(async () => {
      throw new Error("scheduled task nightly is in use");
    });
    render(<ScheduledTasks />);
    await confirmDelete();
    expect((await screen.findByTestId("scheduled-tasks-action-error")).textContent).toBe(
      "scheduled task nightly is in use",
    );
    expect(screen.getByRole("button", { name: t("scheduledTasks.delete") })).not.toHaveAttribute(
      "data-loading",
    );
  });

  it("says a refused delete, rather than taking it for done", async () => {
    deleteSpy.mockImplementationOnce(async () => ({ success: false, message: "refused: in use" }));
    render(<ScheduledTasks />);
    await confirmDelete();
    expect((await screen.findByTestId("scheduled-tasks-action-error")).textContent).toBe(
      "refused: in use",
    );
  });

  it("says why a create raised, and frees the form's save", async () => {
    createSpy.mockImplementationOnce(async () => {
      throw new Error("id nightly is taken");
    });
    mockTasks = [];
    render(<ScheduledTasks />);
    fireEvent.click(screen.getByTestId("scheduled-tasks-toggle-form"));
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.idLabel")), {
      target: { value: "nightly" },
    });
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.nameLabel")), {
      target: { value: "Nightly" },
    });
    fireEvent.change(screen.getByLabelText(t("scheduledTasks.cronLabel")), {
      target: { value: "0 2 * * *" },
    });
    fireEvent.click(screen.getByRole("textbox", { name: t("scheduledTasks.kindLabel") }));
    fireEvent.click(
      within(await screen.findByRole("listbox")).getByText(t("scheduledTasks.kindSql")),
    );
    fireEvent.change(await screen.findByLabelText(t("scheduledTasks.sqlLabel")), {
      target: { value: "SELECT 1" },
    });
    fireEvent.click(screen.getByRole("textbox", { name: t("scheduledTasks.roleLabel") }));
    fireEvent.click(await screen.findByRole("option", { name: "ops", hidden: true }));
    fireEvent.click(screen.getByTestId("scheduled-tasks-submit"));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("id nightly is taken")).toBeTruthy();
    // The form stays open to correct, its save free again.
    expect(screen.getByTestId("scheduled-tasks-submit")).not.toHaveAttribute("data-loading");
  });
});
