// Copyright (c) 2026 Kenneth Stott
// Canary: 6f1a8d24-9b5e-4c73-a2d0-3e7b9c1f5a48
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The explorer's own view settings, in its side rail: how many nodes a query draws.

import { NumberInput } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface GraphViewSettingsProps {
  maxNodes: number;
  /** The server's drawing ceiling; null until graph-schema has said it. */
  nodeCap: number | null;
  onMaxNodesChange: (n: number) => void;
}

export function GraphViewSettings({ maxNodes, nodeCap, onMaxNodesChange }: GraphViewSettingsProps) {
  const { t } = useTranslation();
  return (
    <div className="graph-schema-section">
      <div className="graph-schema-heading">{t("graphSidebar.tabSettings")}</div>
      <NumberInput
        className="graph-view-setting"
        size="xs"
        label={t("graphSidebar.maxNodes")}
        description={
          nodeCap === null ? undefined : t("graphSidebar.maxNodesHint", { ceiling: nodeCap })
        }
        value={nodeCap === null ? maxNodes : Math.min(maxNodes, nodeCap)}
        min={1}
        max={nodeCap ?? undefined}
        clampBehavior="strict"
        allowDecimal={false}
        allowNegative={false}
        onChange={(v) => {
          if (typeof v === "number" && Number.isInteger(v) && v > 0) onMaxNodesChange(v);
        }}
        data-testid="graph-max-nodes"
      />
    </div>
  );
}
