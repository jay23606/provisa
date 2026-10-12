// Copyright (c) 2026 Kenneth Stott
// Canary: 4c7e1a93-8d2f-4b56-a3e0-9f1d6b2c8e47
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { NumberInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormField } from "../../components/form/FormLayout";
import { MultiSelect } from "../../components/MultiSelect";
import type { Role } from "../../types/auth";
import { DataQualityPanel } from "./DataQualityPanel";

interface CheckerFieldsProps {
  checker: string;
  sourceId: string;
  contractText: string;
  onContractChange: (text: string) => void;
  onDatasetChange: (dataset: string | null) => void;
  scanInterval: string;
  onScanIntervalChange: (seconds: string) => void;
  roles: Role[];
  visibleTo: string[];
  onVisibleToChange: (roles: string[]) => void;
}

/** A checker table's registration: its contract, how often it scans, and who sees its results. */
export function CheckerFields(props: CheckerFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      {/* REQ-1663: the contract panel IS the table picker for a checker source — its dataset
          select names the governed table to scan, and the rules are authored right here. */}
      <FormField size="full">
        <div data-testid="register-table-dq">
          <DataQualityPanel
            checker={props.checker}
            sourceId={props.sourceId}
            contractText={props.contractText}
            onChange={props.onContractChange}
            onDatasetChange={props.onDatasetChange}
          />
        </div>
      </FormField>
      {/* REQ-1443: each scan appends its results; the table scans every this many seconds. */}
      <FormField help={t("registerTableForm.dqScanIntervalHint")} size="short">
        <NumberInput
          data-testid="register-table-dq-scan-interval"
          label={t("registerTableForm.dqScanIntervalLabel")}
          min={1}
          required
          value={props.scanInterval === "" ? "" : Number(props.scanInterval)}
          onChange={(v) => props.onScanIntervalChange(v === "" ? "" : String(v))}
        />
      </FormField>
      <FormField size="long">
        <MultiSelect
          options={props.roles.map((r) => ({ id: r.id, label: r.id }))}
          value={props.visibleTo}
          onChange={props.onVisibleToChange}
          label={t("registerTableForm.dqVisibleToLabel")}
        />
      </FormField>
    </>
  );
}
