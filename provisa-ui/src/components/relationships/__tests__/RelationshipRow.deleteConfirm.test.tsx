// Copyright (c) 2026 Kenneth Stott
// Canary: 07559984-ee19-4b8e-8e32-38c1b3588f4a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A relationship's trash icon asks before it deletes: the shared confirmation names the
// relationship, and the row's onDelete runs only on confirm.

import { describe, it, expect, vi } from "vitest";
import { Table } from "@mantine/core";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { render } from "../../../test-utils/render";
import { RelationshipRow } from "../RelationshipRow";
import type { ComponentProps } from "react";

type Props = ComponentProps<typeof RelationshipRow>;

function row(onDelete: () => void) {
  const props = {
    rel: {
      id: "orders-to-customers",
      sourceTableId: 1,
      targetTableId: 2,
      sourceTableName: "orders",
      targetTableName: "customers",
      sourceColumn: "customer_id",
      targetColumn: "id",
      cardinality: "many-to-one",
    },
    isExpanded: true,
    onToggle: vi.fn(),
    editingRel: null,
    setEditingRel: vi.fn(),
    canManage: true,
    onStartEdit: vi.fn(),
    onReverse: vi.fn(),
    onDelete,
    onEditSave: vi.fn(),
    saving: null,
    tables: [],
    functions: [],
    tableDomainById: {},
    domainsEnabled: true,
  } as unknown as Props;
  return (
    <Table>
      <Table.Tbody>
        <RelationshipRow {...props} />
      </Table.Tbody>
    </Table>
  );
}

describe("RelationshipRow: deleting a relationship", () => {
  it("asks first, naming it, and deletes only on confirm", async () => {
    const onDelete = vi.fn();
    render(row(onDelete));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText('Delete relationship "orders-to-customers"?')).toBeTruthy();
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
  });

  it("deletes nothing on cancel", async () => {
    const onDelete = vi.fn();
    render(row(onDelete));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onDelete).not.toHaveBeenCalled();
  });
});
