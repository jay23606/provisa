// Copyright (c) 2026 Kenneth Stott
// Canary: d3b97787-354f-4b5b-9a29-89d21358fd5e
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Select, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormField } from "../../components/form/FormLayout";
import type { ColumnForm } from "./types";

/**
 * The columns in the short register step: every discovered column is registered with its
 * discovered type, so they are counted, not listed. A column discovery could not type is the one
 * thing about them asked here, a type each, because the server refuses a column with none.
 */
export function UntypedColumns({
  columns,
  untypedAtDiscovery,
  irTypes,
  loading,
  onType,
}: {
  columns: ColumnForm[];
  /** The columns discovery could not type: each keeps its picker once a type is chosen. */
  untypedAtDiscovery: string[];
  irTypes: string[];
  loading: boolean;
  onType: (index: number, dataType: string) => void;
}) {
  const { t } = useTranslation();
  if (loading)
    return (
      <FormField size="full">
        <Text size="sm" c="dimmed" data-testid="register-table-columns-loading">
          {t("registerTableForm.columnsLabel")} {t("registerTableForm.columnsLoading")}
        </Text>
      </FormField>
    );
  if (columns.length === 0) return null;
  const untyped = columns.flatMap((c, i) =>
    untypedAtDiscovery.includes(c.name) ? [{ c, i }] : [],
  );
  return (
    <FormField size="full">
      <Stack gap="xs" data-testid="register-table-columns-summary">
        <Text size="sm" c="dimmed">
          {t("registerTableForm.shortColumns", {
            count: columns.length,
            names: columns.map((c) => c.name).join(", "),
          })}
        </Text>
        {untyped.length > 0 && (
          <>
            <Text size="sm">{t("registerTableForm.shortUntyped")}</Text>
            {untyped.map(({ c, i }) => (
              <Select
                key={c.name}
                label={c.name}
                data={irTypes.map((v) => ({ value: v, label: v }))}
                value={c.dataType || null}
                onChange={(v) => v && onType(i, v)}
                searchable
                comboboxProps={{ withinPortal: true }}
                styles={{ input: { fontFamily: "monospace" }, root: { maxWidth: "20rem" } }}
                data-testid={`register-table-type-${c.name}`}
              />
            ))}
          </>
        )}
      </Stack>
    </FormField>
  );
}
