// Copyright (c) 2026 Kenneth Stott
// Canary: b467743d-212f-4bce-af41-82de822ddf70
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Text } from "@mantine/core";
import type { TFunction } from "i18next";
import type { DataProduct, RegisteredTable, Source } from "../../types/admin";
import { DQ_CHECKERS } from "../../types/admin";
import type { DetailField } from "../../components/detail/DetailFields";

// What a table's sections say of a field, shared by the read view and the edit form.

/** The change signals a table may choose, as the edit form lists them. */
export function changeSignalChoices(t: TFunction) {
  return [
    { value: "", label: t("tableEditForm.csInherit") },
    { value: "ttl", label: t("tableEditForm.csTtl") },
    { value: "probe", label: t("tableEditForm.csProbe") },
    { value: "ttl_probe", label: t("tableEditForm.csTtlProbe") },
    { value: "native", label: t("tableEditForm.csNative") },
    { value: "debezium", label: t("tableEditForm.csDebezium") },
    { value: "kafka", label: t("tableEditForm.csKafka") },
  ];
}

/** Whether the table's source is a data-quality checker: its table holds that checker's scans. */
export function isCheckerSource(source: Source | undefined): boolean {
  return (
    source != null && (DQ_CHECKERS as readonly string[]).includes((source.type ?? "").toLowerCase())
  );
}

/** A value that is not set, said in the dimmed text of a default. */
export function unset(text: string) {
  return (
    <Text span size="sm" c="dimmed">
      {text}
    </Text>
  );
}

/** A tick read as words. */
export function yesNo(t: TFunction, value: boolean) {
  return value ? t("detailFields.yes") : t("detailFields.no");
}

/** The data product line of Associations, read-only. */
export function dataProductField(
  t: TFunction,
  table: RegisteredTable,
  dataProducts: DataProduct[],
): DetailField {
  return {
    label: t("tableEditForm.dataProductLabel"),
    testId: "table-read-view-product",
    value:
      table.productId == null
        ? unset(t("tableEditForm.dataProductNone"))
        : (dataProducts.find((p) => p.id === table.productId)?.name ?? table.productId),
  };
}
