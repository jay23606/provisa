// Copyright (c) 2026 Kenneth Stott
// Canary: 5e8964b8-313e-4c7f-9f22-86b77649658d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useTranslation } from "react-i18next";
import { ActionIcon, Button, Stack, Text, Textarea, Title } from "@mantine/core";
import { FieldGroup, FormField, FormLayout } from "../../form/FormLayout";

// REQ-1939, ASSERTIONS: statements over the generated tables, each returning true or false. Each
// runs after generation and its result is reported; none rejects or alters the generated data.
export function DatasetAssertions({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <FormLayout data-testid="synthetic-assertions">
      <FormField size="full">
        <Stack gap={2}>
          <Title order={6}>{t("syntheticDatasets.assertionsTitle")}</Title>
          <Text size="xs" c="dimmed">
            {t("syntheticDatasets.assertionsHelp")}
          </Text>
        </Stack>
      </FormField>
      {value.map((a, i) => (
        // One entry of the list: the statement and its remove, level with each other.
        <FieldGroup
          row
          className="form-field-group--bare"
          key={i}
          data-testid={`synthetic-assertion-${i}`}
        >
          <FormField size="full">
            <Textarea
              aria-label={t("syntheticDatasets.assertion")}
              autosize
              minRows={1}
              placeholder="SELECT COUNT(*) = 0 FROM sales.orders WHERE amount < 0"
              value={a}
              onChange={(e) => {
                const v = e.currentTarget.value;
                onChange(value.map((x, j) => (j === i ? v : x)));
              }}
            />
          </FormField>
          <ActionIcon
            variant="subtle"
            aria-label={t("syntheticDatasets.remove")}
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            ×
          </ActionIcon>
        </FieldGroup>
      ))}
      <FormField size="full">
        <Button
          size="xs"
          variant="light"
          onClick={() => onChange([...value, ""])}
          data-testid="synthetic-add-assertion"
        >
          {t("syntheticDatasets.addAssertion")}
        </Button>
      </FormField>
    </FormLayout>
  );
}
