// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Alert, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import type { RefreshPolicySummary, RegisteredTable, Source } from "../../types/admin";
import { replicateLabel } from "../../components/admin/replicate";
import { useRegionChoices } from "../../hooks/useRegionQueries";
import { NAMING_CONVENTIONS } from "./constants";
import { DetailFields, type DetailField } from "./DetailFields";
import { changeSignalChoices, isCheckerSource, unset, yesNo } from "./tableSectionFields";

// A table's sections read-only: the read view shows them, and so does the edit form to a caller
// who may change only how columns are hidden. Each lists the fields its edit tab has, in the same
// order and under the same labels; a value not set says what applies instead.

/** A table's effective refresh and serving policy, as the server derives it. */
export function RefreshPolicyAlert({ policy }: { policy: RefreshPolicySummary }) {
  const { t } = useTranslation();
  return (
    <Alert
      // REQ-1143: `serving` drives the color; a non-null `warning` flags a setting that has no
      // effect on this engine or an accidental frozen table.
      color={
        policy.warning
          ? "yellow"
          : policy.serving === "live"
            ? "blue"
            : policy.serving === "scheduled"
              ? "teal"
              : policy.serving === "cache"
                ? "gray"
                : "orange"
      }
      title={t("tableEditForm.refreshPolicyTitle")}
      style={{ marginBottom: "0.75rem" }}
      data-testid="refresh-policy-summary"
    >
      <Text size="sm">{policy.text}</Text>
      {policy.warning && (
        <Text size="sm" c="yellow.8" mt={4} fw={500}>
          ⚠ {policy.warning}
        </Text>
      )}
    </Alert>
  );
}

export function IdentityRead({ table }: { table: RegisteredTable }) {
  const { t } = useTranslation();
  const regions = useRegionChoices().regions;
  const naming =
    NAMING_CONVENTIONS.find((nc) => nc.value === (table.gqlNamingConvention ?? ""))?.label ??
    table.gqlNamingConvention;
  const fields: DetailField[] = [
    { label: t("tableSections.source"), value: table.sourceId },
    { label: t("tableSections.schema"), value: table.schemaName },
    { label: t("tableSections.table"), value: table.tableName },
    { label: t("tableSections.domain"), value: table.domainId },
    {
      label: t("tableEditForm.sqlAliasLabel"),
      value: table.alias ?? unset(t("tableReadView.none")),
    },
    { label: t("tableEditForm.namingConventionLabel"), value: naming },
    {
      label: t("tableEditForm.descriptionLabel"),
      value: table.description || unset(t("tableReadView.none")),
      testId: "table-identity-description",
    },
    { label: t("tableEditForm.draftLabel"), value: yesNo(t, table.draft) },
    ...(regions.length > 0
      ? [{ label: t("regionSelect.label"), value: table.region ?? unset(t("regionSelect.none")) }]
      : []),
    ...(table.apiEndpoint
      ? [{ label: t("tableEditForm.apiEndpointLabel"), value: <code>{table.apiEndpoint}</code> }]
      : []),
  ];
  return <DetailFields fields={fields} testId="table-identity" />;
}

export function LoadRead({ table, source }: { table: RegisteredTable; source?: Source }) {
  const { t } = useTranslation();
  const isView = table.viewSql != null;
  const signal = table.changeSignal ?? "";
  const probing = signal === "probe" || signal === "ttl_probe";
  const loadProtected = table.loadProtected ?? source?.loadProtected ?? false;
  const fields: DetailField[] = [
    {
      label: t("tableEditForm.changeSignalLabel"),
      value: changeSignalChoices(t).find((c) => c.value === signal)?.label ?? signal,
    },
    ...(probing
      ? [
          {
            label: t("tableEditForm.probeTypeLabel"),
            value: table.probeType ?? t("tableEditForm.probeTypeAuto"),
          },
          {
            label: t("tableEditForm.freshnessProbeLabel"),
            value: table.probeQuery ? (
              <code>{table.probeQuery}</code>
            ) : (
              unset(t("tableReadView.none"))
            ),
          },
        ]
      : []),
    ...(isView
      ? [
          { label: t("tableEditForm.materializedViewLabel"), value: yesNo(t, table.materialize) },
          ...(table.materialize
            ? [
                {
                  label: t("tableEditForm.refreshIntervalLabel"),
                  value: String(table.mvRefreshInterval),
                },
              ]
            : []),
        ]
      : [
          {
            label: t("tableEditForm.cacheTtlLabel"),
            value:
              table.cacheTtl != null
                ? String(table.cacheTtl)
                : unset(
                    source?.cacheTtl != null
                      ? t("tableSections.fromSource", { value: source.cacheTtl })
                      : t("tableReadView.none"),
                  ),
          },
          {
            label: t("replicateSelect.label"),
            value:
              table.loadProtected === true
                ? t("replicateSelect.scheduled")
                : replicateLabel(t, table.replicate),
          },
          {
            label: t("tableEditForm.roleTtlLabel"),
            value:
              table.roleTtl.length > 0
                ? table.roleTtl.map((r) => `${r.role}: ${r.ttl}`).join(", ")
                : unset(t("tableReadView.none")),
          },
          ...(loadProtected
            ? [
                {
                  label: t("tableEditForm.offPeakWindowLabel"),
                  value: table.offPeakWindow ?? unset(t("tableSections.fromSourceAsIs")),
                },
                {
                  label: t("tableEditForm.offPeakTzLabel"),
                  value: table.offPeakTz ?? unset(t("tableSections.fromSourceAsIs")),
                },
              ]
            : []),
        ]),
    { label: t("tableEditForm.delta.enable"), value: yesNo(t, table.delta != null) },
    { label: t("liveDeliveryFieldset.enableLabel"), value: yesNo(t, table.live != null) },
  ];
  return (
    <>
      {table.refreshPolicySummary && <RefreshPolicyAlert policy={table.refreshPolicySummary} />}
      <DetailFields fields={fields} testId="table-load" />
    </>
  );
}

export function QueryRead({ table }: { table: RegisteredTable }) {
  const { t } = useTranslation();
  const fields: DetailField[] = [
    { label: t("tableEditForm.enableAggregatesLabel"), value: yesNo(t, table.enableAggregates) },
    { label: t("tableEditForm.enableGroupByLabel"), value: yesNo(t, table.enableGroupBy) },
    {
      label: t("columnPresetsEditor.label"),
      value:
        table.columnPresets.length > 0
          ? table.columnPresets
              .map((p) => `${p.column} = ${p.source === "literal" ? p.value : p.source}`)
              .join(", ")
          : unset(t("tableReadView.none")),
    },
    {
      label: t("tableReadView.writable"),
      testId: "table-read-view-writable",
      value:
        table.writeOps.length > 0
          ? table.writeOps.map((op) => op.toUpperCase()).join(", ")
          : unset(t("tableReadView.none")),
    },
    ...(table.watermarkColumn
      ? [{ label: t("tableReadView.watermarkColumn"), value: <code>{table.watermarkColumn}</code> }]
      : []),
    ...(table.queryTemplate
      ? [
          {
            label: t("tableReadView.queryTemplate"),
            testId: "table-read-view-query-template",
            value: <code className="detail-code">{table.queryTemplate}</code>,
          },
        ]
      : []),
    ...(table.viewSql
      ? [
          {
            label: t("tableReadView.viewSql"),
            value: <code className="detail-code">{table.viewSql}</code>,
          },
        ]
      : []),
  ];
  return <DetailFields fields={fields} testId="table-query" />;
}

export function QualityRead({ table, source }: { table: RegisteredTable; source?: Source }) {
  const { t } = useTranslation();
  const checker = isCheckerSource(source);
  const fields: DetailField[] = [
    ...(checker
      ? [
          {
            label: t("dataQualityPanel.title"),
            value: table.dqContract
              ? t("tableSections.contractSet")
              : unset(t("tableReadView.none")),
          },
        ]
      : source?.type === "data_profiler"
        ? []
        : [
            {
              label: t("profilerPanel.title"),
              value: table.profilerSourceId ?? unset(t("tableReadView.none")),
            },
          ]),
    {
      label: t("uniquesPanel.title"),
      value:
        (table.uniqueConstraints ?? []).length > 0
          ? table.uniqueConstraints.map((u) => `${u.name} (${u.columns.join(", ")})`).join("; ")
          : unset(t("tableReadView.none")),
    },
  ];
  return <DetailFields fields={fields} testId="table-quality" />;
}
