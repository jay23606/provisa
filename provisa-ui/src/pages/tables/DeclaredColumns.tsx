// Copyright (c) 2026 Kenneth Stott
// Canary: 36c233ae-d713-4ab0-b97f-862288ea7cf0
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1924: the columns of an OpenAPI table whose operation declares no response schema, declared
// by the steward: each a name and a type. A sample answer (the operation called once with the
// parameter values given here) may suggest some; the steward keeps, edits or removes each. The
// operation's parameters stay as they are, listed with the table's other columns.

import { useState } from "react";
import { useLazyQuery } from "@apollo/client/react";
import { ActionIcon, Alert, Button, Group, Select, Stack, Text, TextInput } from "@mantine/core";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SampleOpenapiColumns } from "../../hooks/admin.graphql";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import { Tip } from "../../components/Tip";
import { blankColumn, type ColumnForm } from "./types";

/** A parameter column's name (``_nf_<name>``) as the parameter is called. */
const parameterName = (column: string) => column.replace(/^_nf_/, "");

export function DeclaredColumns({
  sourceId,
  tableName,
  columns,
  setColumns,
  irTypes,
  visibleTo,
}: {
  sourceId: string;
  tableName: string;
  columns: ColumnForm[];
  setColumns: (columns: ColumnForm[]) => void;
  irTypes: string[];
  visibleTo: string[];
}) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [sample, { loading }] = useLazyQuery<{
    sampleOpenapiColumns: { name: string; dataType: string }[];
  }>(SampleOpenapiColumns, { fetchPolicy: "no-cache" });
  const parameters = columns.filter((c) => c.nativeFilterType);
  const declared = columns.map((c, i) => [c, i] as const).filter(([c]) => !c.nativeFilterType);

  const change = (i: number, patch: Partial<ColumnForm>) =>
    setColumns(columns.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const suggest = async () => {
    setProblem(null);
    const params = Object.fromEntries(
      parameters.map((p) => [parameterName(p.name), values[p.name] ?? ""]),
    );
    const { data, error } = await sample({ variables: { sourceId, tableName, params } });
    if (error) {
      setProblem(error.message);
      return;
    }
    const have = new Set(columns.map((c) => c.name));
    const added = (data?.sampleOpenapiColumns ?? [])
      .filter((s) => !have.has(s.name))
      .map((s) => blankColumn(s.name, s.dataType, visibleTo));
    setColumns([...columns, ...added]);
  };

  return (
    <FormField size="full">
      <Stack gap="xs" data-testid="declared-columns">
        <Text fw={600} fz="sm">
          {t("declaredColumns.title")}
        </Text>
        <Text size="sm" c="dimmed">
          {t("declaredColumns.lead")}
        </Text>
        {declared.map(([c, i]) => (
          <Group key={i} gap="xs" align="flex-end" wrap="nowrap">
            <FieldGroup>
              <FormField size="medium">
                <TextInput
                  label={t("declaredColumns.name")}
                  value={c.name}
                  onChange={(e) => change(i, { name: e.currentTarget.value })}
                  data-testid={`declared-column-name-${i}`}
                />
              </FormField>
              <FormField size="short">
                <Select
                  label={t("declaredColumns.type")}
                  value={c.dataType}
                  data={irTypes}
                  onChange={(v) => change(i, { dataType: v ?? c.dataType })}
                  allowDeselect={false}
                  comboboxProps={{ withinPortal: true }}
                  data-testid={`declared-column-type-${i}`}
                />
              </FormField>
            </FieldGroup>
            <Tip text={t("declaredColumns.remove")} named>
              <ActionIcon
                variant="subtle"
                aria-label={t("declaredColumns.remove")}
                onClick={() => setColumns(columns.filter((_c, j) => j !== i))}
                data-testid={`declared-column-remove-${i}`}
              >
                <Trash2 size={14} />
              </ActionIcon>
            </Tip>
          </Group>
        ))}
        <div>
          <Button
            variant="light"
            onClick={() => setColumns([...columns, blankColumn("", "text", visibleTo)])}
            data-testid="declared-column-add"
          >
            {t("declaredColumns.add")}
          </Button>
        </div>
        <Text fw={600} fz="sm" mt="sm">
          {t("declaredColumns.sampleTitle")}
        </Text>
        {parameters.length > 0 && (
          <FieldGroup>
            {parameters.map((p) => (
              <FormField key={p.name} size="medium">
                <TextInput
                  label={parameterName(p.name)}
                  required={p.nativeFilterRequired === true}
                  value={values[p.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [p.name]: e.currentTarget.value })}
                  data-testid={`declared-sample-param-${parameterName(p.name)}`}
                />
              </FormField>
            ))}
          </FieldGroup>
        )}
        {problem && (
          <Alert color="red" data-testid="declared-sample-problem">
            {problem}
          </Alert>
        )}
        <div>
          <Button
            variant="light"
            loading={loading}
            onClick={() => void suggest()}
            data-testid="declared-sample"
          >
            {t("declaredColumns.sample")}
          </Button>
        </div>
      </Stack>
    </FormField>
  );
}
