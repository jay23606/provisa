// Copyright (c) 2026 Kenneth Stott
// Canary: 499a62df-150f-4f46-8b6a-d0795b755b6b
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1921: where a table's (or view's) data lives and whether it is in service — its region
// and its draft flag, each saved on its own (setTableRegion, setTableDraft).

import { Checkbox } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { RegionSelect } from "../../components/admin/RegionSelect";
import { useRegionChoices } from "../../hooks/useRegionQueries";
import type { RegisteredTable } from "../../types/admin";
import { FormChecks, FormField } from "../../components/form/FormLayout";

export function TablePlacementFields({
  table,
  isView,
  onChange,
}: {
  table: RegisteredTable;
  isView: boolean;
  onChange: (table: RegisteredTable) => void;
}) {
  const { t } = useTranslation();
  const regionChoices = useRegionChoices();
  return (
    <>
      <FormField size="medium">
        <RegionSelect
          value={table.region}
          onChange={(region) => onChange({ ...table, region })}
          regions={regionChoices.regions}
          scope={isView ? "view" : "table"}
          testId="table-region-select"
        />
      </FormField>
      {/* Out of service while checked. */}
      <FormChecks>
        <FormField help={t("tableEditForm.draftHelp")} size="long">
          <Checkbox
            label={t("tableEditForm.draftLabel")}
            checked={table.draft}
            onChange={(e) => onChange({ ...table, draft: e.currentTarget.checked })}
            data-testid="table-draft-checkbox"
          />
        </FormField>
      </FormChecks>
    </>
  );
}
