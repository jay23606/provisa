// Copyright (c) 2026 Kenneth Stott
// Canary: 41c22c45-1a70-40af-add1-772d4eee90ef
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The load and recency controls of the table edit form: the cache lifetime and its per-role list,
// paging, replication and load protection with its off-peak window.

import { Group, NumberInput, Select, Text } from "@mantine/core";
import { TimeInput } from "@mantine/dates";
import { useTranslation } from "react-i18next";
import type { RegisteredTable, Source } from "../../types/admin";
import type { Role } from "../../types/auth";
import { ReplicateSelect } from "../../components/admin/ReplicateSelect";
import { FormField, FormLayout } from "../../components/form/FormLayout";
import { CollapsibleSection } from "./CollapsibleSection";
import { IANA_TIME_ZONES } from "./constants";
import { FieldLabel } from "./FieldLabel";
import { PagingField } from "./PagingField";
import { ReplicaBuildLine } from "./ReplicaBuildLine";
import { RoleTtlField } from "./RoleTtlField";
import type { CacheTtlEdit } from "./TableEditForm";

export function TableLoadManagementFields({
  editingTable,
  setEditingTable,
  editSource,
  roles,
  cacheTtlEdits,
  setCacheTtlEdits,
  floorTtl,
  ttlSignalError,
  effLoadProtected,
}: {
  editingTable: RegisteredTable;
  setEditingTable: (table: RegisteredTable) => void;
  editSource: Source | undefined;
  roles: Role[];
  cacheTtlEdits: Record<number, CacheTtlEdit>;
  setCacheTtlEdits: React.Dispatch<React.SetStateAction<Record<number, CacheTtlEdit>>>;
  floorTtl: number | null;
  ttlSignalError: boolean;
  effLoadProtected: boolean;
}) {
  const { t } = useTranslation();
  return (
    <FormField size="full">
      <CollapsibleSection
        title={t("tableEditForm.loadManagementTitle")}
        testId="load-management-panel"
        info={{
          label: t("tableEditForm.loadManagementInfoLabel"),
          text: t("tableEditForm.loadManagementInfo"),
        }}
      >
        {/* The operator's load and recency controls, grouped: cache TTL (the floor), the per-role
    TTL list (REQ-1907), materialization and load protection (REQ-826/1141). */}
        <Text size="xs" c="dimmed" data-testid="load-management-help">
          {t("tableEditForm.loadManagementHelp")}
        </Text>
        <FormLayout>
          {/* The three settings share a line; what each one lists or reports follows beneath. */}
          <FormField size="short">
            <NumberInput
              label={
                <FieldLabel
                  text={t("tableEditForm.cacheTtlLabel")}
                  help={t("tableEditForm.cacheTtlHelp")}
                />
              }
              min={0}
              value={
                cacheTtlEdits[editingTable.id]?.value ??
                (editingTable.cacheTtl != null ? editingTable.cacheTtl : "")
              }
              onChange={(v) =>
                setCacheTtlEdits((prev) => ({
                  ...prev,
                  [editingTable.id]: {
                    ...prev[editingTable.id],
                    value: v === "" ? "" : String(v),
                    dirty: true,
                  },
                }))
              }
              placeholder={t("tableEditForm.cacheTtlPlaceholder")}
              error={
                ttlSignalError
                  ? t("tableEditForm.cacheTtlRequiredForSignal", {
                      signal: editingTable.changeSignal ?? editSource?.changeSignal,
                    })
                  : undefined
              }
            />
          </FormField>
          <FormField size="medium">
            <ReplicateSelect
              value={editingTable.replicate}
              onChange={(replicate) => setEditingTable({ ...editingTable, replicate })}
              scope="table"
              loadProtected={editingTable.loadProtected ?? editSource?.loadProtected ?? false}
              testId="table-replicate-select"
            />
          </FormField>
          <FormField size="medium">
            <Select
              // REQ-1141: load protection — scheduled-refresh-only; the query path never pulls the source.
              label={
                <FieldLabel
                  text={t("tableEditForm.loadProtectedLabel")}
                  help={t("tableEditForm.loadProtectedHelp")}
                />
              }
              data={[
                { value: "inherit", label: t("tableEditForm.inheritSource") },
                { value: "on", label: t("tableEditForm.on") },
                { value: "off", label: t("tableEditForm.off") },
              ]}
              value={
                editingTable.loadProtected == null
                  ? "inherit"
                  : editingTable.loadProtected
                    ? "on"
                    : "off"
              }
              onChange={(v) =>
                setEditingTable({
                  ...editingTable,
                  loadProtected: v === "inherit" ? null : v === "on",
                })
              }
              comboboxProps={{ withinPortal: true }}
              allowDeselect={false}
            />
          </FormField>
          <FormField size="full">
            <ReplicaBuildLine
              sourceId={editingTable.sourceId}
              schemaName={editingTable.schemaName}
              tableName={editingTable.tableName}
            />
          </FormField>
          <FormField size="full">
            <RoleTtlField
              rows={editingTable.roleTtl}
              onChange={(roleTtl) => setEditingTable({ ...editingTable, roleTtl })}
              roles={roles}
              floorTtl={floorTtl}
            />
          </FormField>
          {editingTable.pagingKind !== null && (
            <FormField size="full">
              <PagingField
                kind={editingTable.pagingKind}
                paging={editingTable.pagination}
                onChange={(pagination) => setEditingTable({ ...editingTable, pagination })}
                ceilingRows={editingTable.pagingCeilingRows}
              />
            </FormField>
          )}
          {effLoadProtected && (
            <FormField size="full">
              <CollapsibleSection
                title={t("tableEditForm.sourceProtectionPanel")}
                testId="mv-protection-panel"
                defaultOpen
              >
                {/* REQ-1141: off-peak window "HH:MM-HH:MM"; the scheduler refreshes only while it is
      open. Two time widgets (opens/closes) compose the string; both blank = no window. */}
                <FormLayout>
                  <FormField size="medium" data-testid="off-peak-window">
                    <FieldLabel
                      text={t("tableEditForm.offPeakWindowLabel")}
                      help={t("tableEditForm.offPeakWindowHelp")}
                    />
                    <Group gap="xs" grow>
                      <TimeInput
                        aria-label={t("tableEditForm.offPeakOpensAria")}
                        data-testid="off-peak-opens"
                        label={t("tableEditForm.offPeakOpens")}
                        value={(editingTable.offPeakWindow ?? "").split("-")[0] ?? ""}
                        onChange={(e) => {
                          const end = (editingTable.offPeakWindow ?? "").split("-")[1] ?? "";
                          const start = e.currentTarget.value;
                          setEditingTable({
                            ...editingTable,
                            offPeakWindow: start || end ? `${start}-${end}` : null,
                          });
                        }}
                      />
                      <TimeInput
                        aria-label={t("tableEditForm.offPeakClosesAria")}
                        data-testid="off-peak-closes"
                        label={t("tableEditForm.offPeakCloses")}
                        value={(editingTable.offPeakWindow ?? "").split("-")[1] ?? ""}
                        onChange={(e) => {
                          const start = (editingTable.offPeakWindow ?? "").split("-")[0] ?? "";
                          const end = e.currentTarget.value;
                          setEditingTable({
                            ...editingTable,
                            offPeakWindow: start || end ? `${start}-${end}` : null,
                          });
                        }}
                      />
                    </Group>
                  </FormField>
                  <FormField size="medium">
                    <Select
                      // REQ-1141: IANA zone for the off-peak window. Picklist of the runtime's supported zones
                      // (Intl.supportedValuesOf) — the same identifiers ZoneInfo accepts server-side — so the
                      // window can never be saved against an unparseable zone.
                      label={
                        <FieldLabel
                          text={t("tableEditForm.offPeakTzLabel")}
                          help={t("tableEditForm.offPeakTzHelp")}
                        />
                      }
                      data={IANA_TIME_ZONES}
                      value={editingTable.offPeakTz ?? ""}
                      onChange={(v) =>
                        setEditingTable({
                          ...editingTable,
                          offPeakTz: v || null,
                        })
                      }
                      searchable
                      clearable
                      placeholder="UTC"
                      comboboxProps={{ withinPortal: true }}
                    />
                  </FormField>
                </FormLayout>
              </CollapsibleSection>
            </FormField>
          )}
        </FormLayout>
      </CollapsibleSection>
    </FormField>
  );
}
