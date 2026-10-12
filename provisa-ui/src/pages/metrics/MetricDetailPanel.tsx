// Copyright (c) 2026 Kenneth Stott
// Canary: b77ac0bf-d035-44e8-b4c7-bab6145c8e69
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import React from "react";
import { useTranslation } from "react-i18next";
import { ActionIcon, Group, Stack, Text } from "@mantine/core";
import { Pencil, Trash2 } from "lucide-react";
import type { Metric } from "../../types/admin";
import { PanelActions } from "../../components/list/SplitPane";
import { Tip } from "../../components/Tip";

interface MetricDetailPanelProps {
  m: Metric;
  dependentViews: string[];
  onEdit: () => void;
  onDelete: () => void;
}

// A metric's Edit and Delete. In the page's detail panel they sit in its pinned head
// (PanelActions); the form's Save and Cancel take their place while it is open.
function MetricActions({
  m,
  onEdit,
  onDelete,
}: {
  m: Metric;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <PanelActions>
      <fieldset className="panel-action-set">
        <Group gap="xs">
          <Tip text={t("metricsPage.editMetric", { name: m.name })} named>
            <ActionIcon
              aria-label={t("metricsPage.editMetric", { name: m.name })}
              data-testid={`metric-detail-edit-${m.name}`}
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
            >
              <Pencil size={14} />
            </ActionIcon>
          </Tip>
          <Tip text={t("metricsPage.deleteMetric", { name: m.name })} named>
            <ActionIcon
              color="red"
              aria-label={t("metricsPage.deleteMetric", { name: m.name })}
              data-testid={`metric-detail-delete-${m.name}`}
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              <Trash2 size={14} />
            </ActionIcon>
          </Tip>
        </Group>
      </fieldset>
    </PanelActions>
  );
}

// Row-click detail view for a metric — detail-then-edit: the read-only facts, with Edit and
// Delete in the panel's head.
export function MetricDetailPanel({ m, dependentViews, onEdit, onDelete }: MetricDetailPanelProps) {
  const { t } = useTranslation();

  const rows: [string, React.ReactNode][] = [
    [
      "expression",
      <Text key="expr" component="span" size="sm" ff="monospace" style={{ whiteSpace: "pre-wrap" }}>
        {m.expression}
      </Text>,
    ],
    ["datatype", m.datatype || "—"],
    ["description", m.description || "—"],
    ["aiContext", m.aiContext || "—"],
    ["sourceFact", m.fromFact ?? t("metricsPage.detail.handAuthored")],
    // REQ-1958: null is "not shown to you" (no view_governance), not "granted to everyone".
    [
      "visibleTo",
      m.visibleTo === null
        ? t("tableReadView.notShown")
        : m.visibleTo.length
          ? m.visibleTo.join(", ")
          : "*",
    ],
    [
      "dependentViews",
      dependentViews.length ? dependentViews.join(", ") : t("metricsPage.detail.noDependents"),
    ],
  ];

  return (
    <Stack gap="sm" data-testid={`metric-detail-${m.name}`}>
      <MetricActions m={m} onEdit={onEdit} onDelete={onDelete} />
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "max-content 1fr",
          gap: "0.25rem 1rem",
          margin: 0,
          color: "var(--text)",
        }}
      >
        {rows.map(([k, v]) => (
          <React.Fragment key={k}>
            <Text component="dt" c="dimmed" fw={500} size="sm">
              {t(`metricsPage.detail.field.${k}`)}
            </Text>
            <Text component="dd" m={0} size="sm">
              {v}
            </Text>
          </React.Fragment>
        ))}
      </dl>
    </Stack>
  );
}
