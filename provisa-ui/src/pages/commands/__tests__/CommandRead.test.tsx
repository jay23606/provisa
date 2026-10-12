// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A command's panel shows every value of the function or webhook under its form's labels, the
// implementation's own fields for that implementation, and who sees each response column and how
// it is masked.

import { describe, it, expect } from "vitest";
import { render, screen, within } from "../../../test-utils/render";
import type { TrackedFunction, TrackedWebhook } from "../../../api/actions";
import { FunctionRead, WebhookRead } from "../CommandRead";

function fields(testId: string): [string, string][] {
  return within(screen.getByTestId(testId))
    .queryAllByRole("term")
    .map((dt) => [dt.textContent ?? "", dt.nextElementSibling?.textContent ?? ""]);
}

const fn: TrackedFunction = {
  name: "refund_order",
  sourceId: "sales-pg",
  schemaName: "public",
  functionName: "refund",
  returns: "",
  arguments: [{ name: "order_id", type: "Int" }],
  visibleTo: ["support"],
  domainId: "sales",
  description: "Refunds an order",
  kind: "mutation",
  implKind: "http",
  binding: { url: "https://pay.example.com/refund", method: "POST" },
  materialize: true,
  requiresApproval: true,
  writesTable: "public.orders",
  productId: "p1",
  outputColumns: [
    {
      name: "card",
      type: "string",
      visible_to: ["finance"],
      mask_type: "regex",
      mask_pattern: "\\d{12}",
      mask_replace: "****",
      unmasked_to: ["auditor"],
    },
    { name: "status", type: "string" },
  ],
};

const wh: TrackedWebhook = {
  name: "notify_ops",
  url: "https://hooks.example.com/ops",
  method: "POST",
  timeoutMs: 5000,
  returns: null,
  inlineReturnType: [{ name: "ok", type: "Boolean", mask_type: "constant", mask_value: "hidden" }],
  arguments: [],
  visibleTo: [],
  domainId: "ops",
  description: null,
  kind: "query",
  requiresApproval: false,
  approved: false,
};

describe("a function's read view", () => {
  it("shows every value, with the fields of its implementation", () => {
    render(<FunctionRead fn={fn} productName="Refunds" />);
    expect(fields("function-read-fields")).toEqual([
      ["Name", "refund_order"],
      ["Type", "DB Function"],
      ["Kind", "Mutation"],
      ["Domain", "sales"],
      ["Data Product (optional)", "Refunds"],
      ["Implementation", "HTTP endpoint"],
      ["Endpoint URL", "https://pay.example.com/refund"],
      ["Method", "POST"],
      ["Materialize (admin/definer identity)", "Yes"],
      ["Return Type", "Dataset (columns)"],
      ["Visible To (roles, comma-separated)", "support"],
      ["Writes table", "public.orders"],
      ["Requires approval", "Yes"],
      ["Description", "Refunds an order"],
      ["Arguments", "order_id: Int"],
    ]);
    expect(fields("function-read-columns-card")).toEqual([
      ["Visible to (roles, comma-separated; blank = everyone)", "finance"],
      ["Mask", "Regex"],
      ["Pattern", "\\d{12}"],
      ["Replace", "****"],
      ["Unmasked to (roles, comma-separated)", "auditor"],
    ]);
    expect(fields("function-read-columns-status")).toEqual([
      ["Visible to (roles, comma-separated; blank = everyone)", "all"],
      ["Mask", "None"],
      ["Unmasked to (roles, comma-separated)", "—"],
    ]);
  });

  it("shows a source procedure's source, schema and function, and no binding", () => {
    render(
      <FunctionRead
        fn={{ ...fn, implKind: "source_procedure", binding: {}, returns: "public.refunds" }}
        productName={null}
      />,
    );
    const shown = Object.fromEntries(fields("function-read-fields"));
    expect(shown["Source"]).toBe("sales-pg");
    expect(shown["Schema"]).toBe("public");
    expect(shown["Data Product (optional)"]).toBe("—");
    expect(shown["Return Type"]).toBe("Registered Table");
    expect(shown["Returns (table)"]).toBe("public.refunds");
    expect(shown["Endpoint URL"]).toBeUndefined();
    expect(shown["Materialize (admin/definer identity)"]).toBeUndefined();
    expect(screen.queryByTestId("function-read-columns-card")).toBeNull();
  });
});

describe("a webhook's read view", () => {
  it("shows every value, and its inline response fields' governance", () => {
    render(<WebhookRead wh={wh} />);
    expect(fields("webhook-read-fields")).toEqual([
      ["Name", "notify_ops"],
      ["Type", "Webhook"],
      ["Kind", "Query"],
      ["Domain", "ops"],
      ["Status", "Pending approval"],
      ["URL", "https://hooks.example.com/ops"],
      ["Method", "POST"],
      ["Timeout (ms)", "5000"],
      ["Returns (table, optional)", "—"],
      ["Visible To (roles, comma-separated)", "all"],
      ["Requires approval", "No"],
      ["Description", "—"],
      ["Arguments", "—"],
    ]);
    expect(fields("webhook-read-columns-ok")).toEqual([
      ["Visible to (roles, comma-separated; blank = everyone)", "all"],
      ["Mask", "Constant"],
      ["Value", "hidden"],
      ["Unmasked to (roles, comma-separated)", "—"],
    ]);
  });
});
