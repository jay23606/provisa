// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Tabs } from "@mantine/core";
import { useTranslation } from "react-i18next";
import type { SourceSection } from "./sourceSections";

/** A source's sections, one tab each: those its kind of source has. */
export function SourceSectionTabs({
  value,
  shown,
  onChange,
}: {
  value: SourceSection;
  shown: SourceSection[];
  onChange: (section: SourceSection) => void;
}) {
  const { t } = useTranslation();
  return (
    <Tabs value={value} onChange={(v) => v && onChange(v as SourceSection)} mb="sm">
      <Tabs.List aria-label={t("sourceSections.label")}>
        {shown.map((section) => (
          <Tabs.Tab key={section} value={section} data-testid={`source-section-${section}`}>
            {t(`sourceSections.${section}`)}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs>
  );
}
