// Copyright (c) 2026 Kenneth Stott
// Canary: b3369936-efb2-4360-9f55-b35811c4c45e
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Table data preview modal — thin shell around the shared GovernedTableViewer.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Loader, Modal, ScrollArea, Table, Text } from "@mantine/core";
import { previewTable } from "../api/admin";
import type { RegisteredTable } from "../types/admin";
import { GovernedTableViewer } from "./GovernedTableViewer";

interface TablePreviewModalProps {
  table: RegisteredTable | null;
  // The role the preview is read as (a draft's preview names it to the server).
  role?: string | null;
  onClose: () => void;
}

type DraftRows =
  | { state: "loading" }
  | { state: "failed"; message: string }
  | { state: "read"; columns: string[]; rows: Record<string, unknown>[] };

/** REQ-1921: the preview of a DRAFT. A draft is in no schema, so no statement reads it; its
 * first rows come from the one admin read a draft takes, as the caller, and are shown as they
 * are — no filters or paging, which are statements too. */
function DraftPreviewRows({ table, role }: { table: RegisteredTable; role: string | null }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<DraftRows>({ state: "loading" });

  useEffect(() => {
    let current = true;
    if (!role) return;
    previewTable(table.id, role).then(
      (r) => current && setRows({ state: "read", columns: r.columns, rows: r.rows }),
      (e: unknown) =>
        current &&
        setRows({ state: "failed", message: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      current = false;
    };
  }, [table.id, role]);

  return (
    <>
      <Text size="sm" c="dimmed" mb="xs" data-testid="table-preview-draft-note">
        {t("tableReadView.draftPreviewNote")}
      </Text>
      {rows.state === "loading" && <Loader size="sm" />}
      {rows.state === "failed" && (
        <Alert color="red" data-testid="table-preview-draft-error">
          {rows.message}
        </Alert>
      )}
      {rows.state === "read" && (
        <ScrollArea h="62vh">
          <Table striped withTableBorder data-testid="table-preview-draft-rows">
            <Table.Thead>
              <Table.Tr>
                {rows.columns.map((c) => (
                  <Table.Th key={c}>{c}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.rows.map((row, i) => (
                <Table.Tr key={i}>
                  {rows.columns.map((c) => (
                    <Table.Td key={c}>{row[c] == null ? "" : String(row[c])}</Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
    </>
  );
}

export function TablePreviewModal({ table, role = null, onClose }: TablePreviewModalProps) {
  return (
    <Modal.Root opened={table != null} onClose={onClose} size="90%">
      <Modal.Overlay />
      <Modal.Content data-testid="table-preview-modal">
        <Modal.Header>
          <Modal.Title>
            <Text fw={600} ff="monospace">
              {table ? table.alias || table.tableName : ""}
            </Text>
          </Modal.Title>
          <Modal.CloseButton />
        </Modal.Header>
        <Modal.Body>
          {table && (
            <div style={{ height: "70vh", display: "flex", flexDirection: "column" }}>
              {table.draft ? (
                <DraftPreviewRows key={table.id} table={table} role={role} />
              ) : (
                <GovernedTableViewer key={table.id} table={table} />
              )}
            </div>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal.Root>
  );
}
