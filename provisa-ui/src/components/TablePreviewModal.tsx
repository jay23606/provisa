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

import { useTranslation } from "react-i18next";
import { Modal, Text } from "@mantine/core";
import type { RegisteredTable } from "../types/admin";
import { GovernedTableViewer } from "./GovernedTableViewer";

interface TablePreviewModalProps {
  table: RegisteredTable | null;
  // The role the preview is read as (a draft's preview names it to the server).
  role?: string | null;
  onClose: () => void;
}

export function TablePreviewModal({ table, role = null, onClose }: TablePreviewModalProps) {
  const { t } = useTranslation();
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
              {/* REQ-1921: a draft's preview is the same viewer; it reads through the admin
                  preview, as the caller, and says whom the table is not yet shown to. */}
              {table.draft && (
                <Text size="sm" c="dimmed" mb="xs" data-testid="table-preview-draft-note">
                  {t("tableReadView.draftPreviewNote")}
                </Text>
              )}
              <GovernedTableViewer key={table.id} table={table} role={role} />
            </div>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal.Root>
  );
}
