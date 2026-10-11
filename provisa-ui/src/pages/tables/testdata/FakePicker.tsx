// Copyright (c) 2026 Kenneth Stott
// Canary: daab3203-35a2-4a4b-af64-00a9415b9480
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Select, TextInput } from "@mantine/core";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { FakeCatalog } from "../../../api/fakes";
import { chosen, compose, type ArgValues, type Choice } from "./declaration";
import { FieldGroup, FormField } from "../../../components/form/FormLayout";

// REQ-1494: a kind of fake or fake method picked by name within its category, its arguments
// filled in, written as the declaration the column saves. The declaration stays editable as text.
export function FakePicker({
  catalog,
  label,
  value,
  onChange,
  rule,
  testId,
}: {
  catalog: FakeCatalog;
  label: string;
  value: string;
  onChange: (declaration: string) => void;
  // A synthetic rule may also be a cross-row kind; a fake may not.
  rule: boolean;
  testId: string;
}) {
  const { t } = useTranslation();
  const [choice, setChoice] = useState<Choice | null>(chosen(catalog, value));
  const [args, setArgs] = useState<ArgValues>({});
  const groups = new Map<string, { value: string; label: string }[]>();
  for (const k of catalog.kinds) {
    if (k.ruleOnly && !rule) continue;
    const group = t(`testData.kindCategory.${k.category}`);
    groups.set(group, [...(groups.get(group) ?? []), { value: `kind:${k.name}`, label: k.name }]);
  }
  for (const m of catalog.methods) {
    const group = t("testData.methodCategory", { category: m.category });
    groups.set(group, [...(groups.get(group) ?? []), { value: `method:${m.name}`, label: m.name }]);
  }
  const data = [...groups].map(([group, items]) => ({ group, items }));
  const argNames: string[] =
    choice === null
      ? []
      : choice.type === "kind"
        ? (catalog.kinds.find((k) => k.name === choice.name)?.args ?? []).map((a) => a.name)
        : (catalog.methods.find((m) => m.name === choice.name)?.params ?? []).map((p) => p.name);
  const pick = (next: Choice | null, nextArgs: ArgValues) => {
    setChoice(next);
    setArgs(nextArgs);
    onChange(next ? compose(catalog, next, nextArgs) : "");
  };
  return (
    // One declaration, a row to itself: what is picked, its arguments, and the text they compose.
    <FieldGroup row>
      <FormField size="medium">
        <Select
          label={label}
          searchable
          clearable
          data={data}
          value={choice ? `${choice.type}:${choice.name}` : null}
          onChange={(v) => {
            const [type, name] = (v ?? ":").split(":");
            pick(v ? { type: type as "kind" | "method", name } : null, {});
          }}
          comboboxProps={{ withinPortal: true }}
          data-testid={`${testId}-pick`}
        />
      </FormField>
      {argNames.map((a) => (
        <FormField size="short" key={a}>
          <TextInput
            label={a}
            value={args[a] ?? ""}
            onChange={(e) => choice && pick(choice, { ...args, [a]: e.target.value })}
            data-testid={`${testId}-arg-${a}`}
          />
        </FormField>
      ))}
      <FormField size="long">
        <TextInput
          // Labelled as the boxes beside it are, so it stands level with them.
          label={t("testData.declaration")}
          value={value}
          onChange={(e) => {
            setChoice(chosen(catalog, e.target.value));
            onChange(e.target.value);
          }}
          data-testid={`${testId}-text`}
        />
      </FormField>
    </FieldGroup>
  );
}
