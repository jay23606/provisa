// Copyright (c) 2026 Kenneth Stott
// Canary: 94b44cf7-5220-424d-9b46-c0621e5d41b0
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A column has more attributes than a row has room for, so the column editors of the register and
// edit forms show them a topic at a time: the column's name stays first, and a tab picks which of
// its attributes follow. Every tab edits the same rows; the form's one Save sends them all.

import { Badge, Tabs } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { COLUMN_TABS, type ColumnTab } from "./columnTopics";

/**
 * `errors` counts, per tab, the cells that hold something Save will refuse: a tab that is not in
 * view shows its count on its label, so a refused Save is never about something out of sight.
 */
export function ColumnTabs({
  value,
  onChange,
  shown = COLUMN_TABS,
  errors = {},
  nested = false,
}: {
  value: ColumnTab;
  onChange: (tab: ColumnTab) => void;
  shown?: ColumnTab[];
  errors?: Partial<Record<ColumnTab, number>>;
  /** Inside a table's Columns section: the smaller second row under the section tabs. */
  nested?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Tabs
      value={value}
      onChange={(v) => v && onChange(v as ColumnTab)}
      mb="xs"
      className={nested ? "column-tabs--nested" : undefined}
    >
      <Tabs.List aria-label={t("tableEditForm.columnTabs.label")}>
        {shown.map((tab) => {
          const count = errors[tab] ?? 0;
          return (
            <Tabs.Tab
              key={tab}
              value={tab}
              data-testid={`column-tab-${tab}`}
              rightSection={
                count > 0 ? (
                  <Badge
                    size="xs"
                    color="red"
                    circle
                    aria-label={t("tableEditForm.columnTabs.errors", { count })}
                    data-testid={`column-tab-${tab}-errors`}
                  >
                    {count}
                  </Badge>
                ) : undefined
              }
            >
              {t(`tableEditForm.columnTabs.${tab}`)}
            </Tabs.Tab>
          );
        })}
      </Tabs.List>
    </Tabs>
  );
}
