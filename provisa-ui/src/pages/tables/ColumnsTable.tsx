// Copyright (c) 2026 Kenneth Stott
// Canary: 5c1e8126-83d6-4b4d-afb2-d8812e3b10fb
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The per-column editor table of the Register Table form, extracted so RegisterTableForm stays
// within its line budget (REQ-788 wiring needed the room). Pure presentation over the form's
// column state; updateCol mutates one column's one field.

import { Tip } from "../../components/Tip";
import { Fragment } from "react";
import { Checkbox, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { MultiSelect } from "../../components/MultiSelect";
import { useTranslation } from "react-i18next";

import { toIrType } from "../../irTypes";
import { NumericSizeInputs } from "./NumericSizeInputs";
import type { Role } from "../../types/auth";
import type { ColumnForm } from "./types";
import { ColumnGlossaryHover, type ColumnDefinitionLine } from "./ColumnGlossaryHover";
import { ColumnTabs } from "./ColumnTabs";
import { METADATA_TABS, useColumnTab } from "./columnTopics";

export function ColumnsTable({
  columns,
  updateCol,
  roles,
  irTypes,
  sourceType,
}: {
  columns: ColumnForm[];
  updateCol: (i: number, key: keyof ColumnForm, value: string | boolean | string[]) => void;
  roles: Role[];
  irTypes: string[];
  sourceType: string;
}) {
  const { t } = useTranslation();
  // A table not registered yet has no test data: its columns' own attributes only.
  const [tab, setTab] = useColumnTab(METADATA_TABS);
  // What Save will refuse, per tab: a selected column with no data type.
  const errors = { type: columns.filter((c) => c.selected && !c.dataType).length };
  const definitionOf = (col: ColumnForm): ColumnDefinitionLine[] => [
    { label: t("registerTableForm.colHeaderColumn"), value: col.name },
    { label: t("registerTableForm.colHeaderAlias"), value: col.alias || "" },
    { label: t("registerTableForm.colHeaderDescription"), value: col.description },
    ...(sourceType === "ingest"
      ? [{ label: t("registerTableForm.colHeaderJsonPath"), value: col.path ?? "" }]
      : []),
    {
      label: t("registerTableForm.colHeaderDataType"),
      value: col.dataType ? toIrType(col.dataType) : "",
    },
    {
      label: t("registerTableForm.colHeaderPk"),
      value: col.isPrimaryKey ? "✓" : "",
    },
    { label: t("registerTableForm.colHeaderScope"), value: col.scope },
    { label: t("registerTableForm.colHeaderVisibleTo"), value: col.visibleTo.join(", ") },
    { label: t("registerTableForm.colHeaderWritableBy"), value: col.writableBy.join(", ") },
    { label: t("registerTableForm.colHeaderMasking"), value: col.maskType },
  ];
  return (
    <>
      <ColumnTabs value={tab} onChange={setTab} shown={METADATA_TABS} errors={errors} />
      <Table.ScrollContainer minWidth={640}>
        <Table striped highlightOnHover withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th></Table.Th>
              <Table.Th>{t("registerTableForm.colHeaderColumn")}</Table.Th>
              {tab === "naming" && (
                <>
                  <Table.Th>{t("registerTableForm.colHeaderAlias")}</Table.Th>
                  <Table.Th w="60%">{t("registerTableForm.colHeaderDescription")}</Table.Th>
                  {sourceType === "ingest" && (
                    <Table.Th>{t("registerTableForm.colHeaderJsonPath")}</Table.Th>
                  )}
                </>
              )}
              {tab === "type" && (
                <>
                  <Table.Th>{t("registerTableForm.colHeaderDataType")}</Table.Th>
                  <Table.Th ta="center">{t("registerTableForm.colHeaderPk")}</Table.Th>
                  <Table.Th>{t("registerTableForm.colHeaderScope")}</Table.Th>
                </>
              )}
              {tab === "access" && (
                <>
                  <Table.Th>{t("registerTableForm.colHeaderVisibleTo")}</Table.Th>
                  <Table.Th>{t("registerTableForm.colHeaderWritableBy")}</Table.Th>
                  <Table.Th>{t("registerTableForm.colHeaderMasking")}</Table.Th>
                </>
              )}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {columns.map((col, i) => (
              <Fragment key={col.name}>
                <Table.Tr>
                  <Table.Td>
                    <Checkbox
                      checked={col.selected}
                      onChange={(e) => updateCol(i, "selected", e.currentTarget.checked)}
                      aria-label={t("registerTableForm.includeColumnAriaLabel", {
                        name: col.name,
                      })}
                      data-testid={`register-table-col-selected-${col.name}`}
                    />
                  </Table.Td>
                  <Table.Td ff="monospace" fz="sm">
                    <ColumnGlossaryHover columnName={col.name} definition={definitionOf(col)}>
                      {/* A raw source column name can run to 60+ characters: it is cut with an
                      ellipsis here, and the hover shows it whole with the rest of the column. */}
                      <Text
                        ff="monospace"
                        fz="sm"
                        truncate="end"
                        maw={220}
                        component="span"
                        style={{ display: "inline-block", verticalAlign: "bottom" }}
                      >
                        {col.name}
                      </Text>
                    </ColumnGlossaryHover>
                  </Table.Td>
                  {tab === "naming" && (
                    <>
                      <Table.Td>
                        <TextInput
                          aria-label={t("registerTableForm.colHeaderAlias")}
                          value={col.alias || ""}
                          onChange={(e) => updateCol(i, "alias", e.currentTarget.value)}
                        />
                      </Table.Td>
                      <Table.Td>
                        <TextInput
                          aria-label={t("registerTableForm.colHeaderDescription")}
                          value={col.description}
                          onChange={(e) => updateCol(i, "description", e.currentTarget.value)}
                          placeholder={t("registerTableForm.descriptionColPlaceholder")}
                        />
                      </Table.Td>
                      {sourceType === "ingest" && (
                        <Table.Td>
                          <TextInput
                            aria-label={t("registerTableForm.colHeaderJsonPath")}
                            value={col.path ?? ""}
                            onChange={(e) => updateCol(i, "path", e.currentTarget.value)}
                            placeholder="payload.order_id"
                            data-testid={`register-table-col-path-${col.name}`}
                          />
                        </Table.Td>
                      )}
                    </>
                  )}
                  {tab === "type" && (
                    <>
                      <Table.Td>
                        <Select
                          aria-label={t("registerTableForm.colHeaderDataType")}
                          placeholder={t("registerTableForm.dataTypePlaceholder")}
                          data={Array.from(
                            new Set([
                              ...(col.dataType ? [toIrType(col.dataType)] : []),
                              ...irTypes,
                            ]),
                          )}
                          value={col.dataType ? toIrType(col.dataType) : null}
                          onChange={(v) => updateCol(i, "dataType", v ?? "")}
                          error={col.selected && !col.dataType}
                          searchable
                          allowDeselect={false}
                          data-testid={`register-table-col-datatype-${col.name}`}
                        />
                        {col.dataType && toIrType(col.dataType) === "numeric" && (
                          <NumericSizeInputs
                            key={col.name}
                            dataType={col.dataType}
                            onChange={(v) => updateCol(i, "dataType", v)}
                            testId={`register-table-col-numeric-size-${col.name}`}
                          />
                        )}
                      </Table.Td>
                      <Table.Td ta="center">
                        <Tip text={t("registerTableForm.primaryKeyTitle")}>
                          <Checkbox
                            checked={col.isPrimaryKey}
                            onChange={(e) => updateCol(i, "isPrimaryKey", e.currentTarget.checked)}
                            aria-label={t("registerTableForm.primaryKeyAriaLabel", {
                              name: col.name,
                            })}
                            data-testid={`register-table-col-pk-${col.name}`}
                          />
                        </Tip>
                      </Table.Td>
                      <Table.Td>
                        <Select
                          aria-label={t("registerTableForm.colHeaderScope")}
                          title={t("registerTableForm.scopeHelp")}
                          data={[
                            { value: "domain", label: t("registerTableForm.scopeDomain") },
                            { value: "public", label: t("registerTableForm.scopePublic") },
                            {
                              value: "restricted",
                              label: t("registerTableForm.scopeRestricted"),
                            },
                          ]}
                          value={col.scope}
                          onChange={(v) => updateCol(i, "scope", v ?? "domain")}
                          allowDeselect={false}
                        />
                      </Table.Td>
                    </>
                  )}
                  {tab === "access" && (
                    <>
                      <Table.Td>
                        <MultiSelect
                          options={roles.map((r) => ({ id: r.id, label: r.id }))}
                          value={col.visibleTo}
                          onChange={(selected) => updateCol(i, "visibleTo", selected)}
                          ariaLabel={t("registerTableForm.colHeaderVisibleTo")}
                        />
                      </Table.Td>
                      <Table.Td>
                        <MultiSelect
                          options={roles.map((r) => ({ id: r.id, label: r.id }))}
                          value={col.writableBy}
                          onChange={(selected) => updateCol(i, "writableBy", selected)}
                          ariaLabel={t("registerTableForm.colHeaderWritableBy")}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Select
                          aria-label={t("registerTableForm.colHeaderMasking")}
                          data={[
                            { value: "", label: t("registerTableForm.maskNone") },
                            { value: "regex", label: t("registerTableForm.maskRegex") },
                            { value: "constant", label: t("registerTableForm.maskConstant") },
                            { value: "truncate", label: t("registerTableForm.maskTruncate") },
                          ]}
                          value={col.maskType}
                          onChange={(v) => updateCol(i, "maskType", v ?? "")}
                          allowDeselect={false}
                        />
                      </Table.Td>
                    </>
                  )}
                </Table.Tr>
                {tab === "access" && col.maskType && (
                  <Table.Tr>
                    <Table.Td></Table.Td>
                    <Table.Td c="dimmed" fz="xs">
                      {t("registerTableForm.maskingRowLabel")}
                    </Table.Td>
                    {col.maskType === "regex" && (
                      <Table.Td colSpan={2}>
                        <Stack gap={4}>
                          <TextInput
                            value={col.maskPattern}
                            onChange={(e) => updateCol(i, "maskPattern", e.currentTarget.value)}
                            placeholder={t("registerTableForm.maskPatternPlaceholder")}
                            aria-label={t("registerTableForm.maskPatternPlaceholder")}
                          />
                          <TextInput
                            value={col.maskReplace}
                            onChange={(e) => updateCol(i, "maskReplace", e.currentTarget.value)}
                            placeholder={t("registerTableForm.maskReplacePlaceholder")}
                            aria-label={t("registerTableForm.maskReplacePlaceholder")}
                          />
                        </Stack>
                      </Table.Td>
                    )}
                    {col.maskType === "constant" && (
                      <Table.Td colSpan={2}>
                        <TextInput
                          value={col.maskValue}
                          onChange={(e) => updateCol(i, "maskValue", e.currentTarget.value)}
                          placeholder={t("registerTableForm.maskValuePlaceholder")}
                          aria-label={t("registerTableForm.maskValuePlaceholder")}
                        />
                      </Table.Td>
                    )}
                    {col.maskType === "truncate" && (
                      <Table.Td colSpan={2}>
                        <Select
                          aria-label={t("registerTableForm.maskPrecisionPlaceholder")}
                          placeholder={t("registerTableForm.maskPrecisionPlaceholder")}
                          data={[
                            { value: "year", label: t("registerTableForm.precisionYear") },
                            { value: "month", label: t("registerTableForm.precisionMonth") },
                            { value: "day", label: t("registerTableForm.precisionDay") },
                            { value: "hour", label: t("registerTableForm.precisionHour") },
                          ]}
                          value={col.maskPrecision || null}
                          onChange={(v) => updateCol(i, "maskPrecision", v ?? "")}
                        />
                      </Table.Td>
                    )}
                    <Table.Td>
                      <TextInput
                        value={col.unmaskedTo}
                        onChange={(e) => updateCol(i, "unmaskedTo", e.currentTarget.value)}
                        placeholder={t("registerTableForm.unmaskedToPlaceholder")}
                        aria-label={t("registerTableForm.unmaskedToPlaceholder")}
                      />
                    </Table.Td>
                  </Table.Tr>
                )}
              </Fragment>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}
