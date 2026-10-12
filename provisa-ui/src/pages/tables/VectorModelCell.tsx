// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2000: a Qdrant collection's vector column names the registered model it is an embedding of
// -- what a similarity search over it and a text written to it are embedded by. The choices are
// the models whose dimensions are the vector's size.

import { Select, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { vectorOf } from "./useVectorModels";

export function VectorModelCell({
  column,
  path,
  value,
  models,
  onChange,
}: {
  column: string;
  path: string | null | undefined;
  value: string | null | undefined;
  models: Record<string, string[]>;
  onChange: (model: string | null) => void;
}) {
  const { t } = useTranslation();
  const vector = vectorOf(path);
  if (vector === null) return null;
  const choices = models[vector] ?? [];
  if (choices.length === 0 && !value) {
    return (
      <Text size="xs" c="dimmed" data-testid={`vector-model-none-${column}`}>
        {t("vectorModelCell.none")}
      </Text>
    );
  }
  return (
    <Select
      aria-label={t("vectorModelCell.label", { column })}
      placeholder={t("vectorModelCell.placeholder")}
      data={Array.from(new Set([...(value ? [value] : []), ...choices]))}
      value={value ?? null}
      onChange={(v) => onChange(v)}
      clearable
      data-testid={`vector-model-${column}`}
    />
  );
}
