// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import type { ReactNode } from "react";
import { Table } from "@mantine/core";
import type { TFunction } from "i18next";
import type { ColumnPreset, RegisteredTable } from "../../types/admin";
import type { DetailField } from "../../components/detail/DetailFields";

// What the Query tab reads of a table's stored settings, under the edit controls' own labels.

/** The values written into a column on every write, as the presets editor lists them. */
function presetsTable(t: TFunction, presets: ColumnPreset[]): ReactNode {
  if (presets.length === 0) return null;
  const source: Record<ColumnPreset["source"], string> = {
    now: t("columnPresetsEditor.sourceNow"),
    header: t("columnPresetsEditor.sourceHeaderOption"),
    literal: t("columnPresetsEditor.sourceLiteral"),
  };
  return (
    <Table className="data-table detail-table" data-testid="table-read-presets">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("columnPresetsEditor.columnHeader")}</Table.Th>
          <Table.Th>{t("columnPresetsEditor.sourceHeader")}</Table.Th>
          <Table.Th>{t("columnPresetsEditor.valueHeader")}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {presets.map((p) => (
          <Table.Tr key={p.column}>
            <Table.Td>
              <code>{p.column}</code>
            </Table.Td>
            <Table.Td>{source[p.source]}</Table.Td>
            <Table.Td>
              {(p.source === "header" ? p.name : p.value) ?? t("detailFields.empty")}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function presetsField(t: TFunction, table: RegisteredTable): DetailField {
  return { label: t("columnPresetsEditor.label"), value: presetsTable(t, table.columnPresets) };
}

/** REQ-1318: a view composed from metrics: what it is made of. A free-hand view has none. */
export function viewMetricsFields(t: TFunction, table: RegisteredTable): DetailField[] {
  const spec = table.viewMetrics;
  if (!spec) return [];
  return [
    { label: t("viewDefinitionForm.fieldMetrics"), value: spec.metrics.join(", ") },
    { label: t("viewDefinitionForm.fieldDimensions"), value: spec.dimensions.join(", ") },
    { label: t("viewDefinitionForm.fieldFilters"), value: spec.filters.join("; ") },
  ];
}
