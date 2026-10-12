// Copyright (c) 2026 Kenneth Stott
// Canary: b0500d07-f832-407c-beeb-03121ba5f723
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1093: table-level UNIQUE constraints editor. An expandable panel; each row is one
// constraint with a Name field and a multi-select checkbox of the table's columns.

import { useTranslation } from "react-i18next";
import { ActionIcon, Accordion, Button, Group, MultiSelect, Text, TextInput } from "@mantine/core";
import { CircleHelp, Plus, X } from "lucide-react";
import type { UniqueConstraint } from "../../types/admin";
import { usePanelState } from "../../hooks/usePanelState";
import { FieldGroup, FormField, FormLayout } from "../form/FormLayout";
import { Tip } from "../Tip";

interface Props {
  uniques: UniqueConstraint[];
  columns: string[];
  onChange: (uniques: UniqueConstraint[]) => void;
  /** Shown open with no expander: where the constraints are a section's own content. */
  flat?: boolean;
}

export function UniquesPanel({ uniques, columns, onChange, flat = false }: Props) {
  const { t } = useTranslation();
  const [panel, setPanel] = usePanelState("uniques");

  const update = (i: number, patch: Partial<UniqueConstraint>) => {
    onChange(uniques.map((u, idx) => (idx === i ? { ...u, ...patch } : u)));
  };
  const remove = (i: number) => onChange(uniques.filter((_, idx) => idx !== i));
  const add = () => onChange([...uniques, { name: "", columns: [] }]);

  const heading = (
    <Group gap={6} align="center">
      {/* Flat, it is a heading on the tab, as bold as the Data Profiler's beside it. */}
      <Text size="sm" fw={flat ? 600 : undefined}>
        {t("uniquesPanel.title")}
      </Text>
      {uniques.length > 0 && (
        <Text size="xs" c="dimmed">
          {t("uniquesPanel.summary", { count: uniques.length })}
        </Text>
      )}
      <Tip text={t("uniquesPanel.infoTooltip")} named>
        <ActionIcon
          component="span"
          variant="subtle"
          color="gray"
          size="xs"
          role="button"
          tabIndex={0}
          aria-label={t("uniquesPanel.infoTooltip")}
          onClick={(e) => e.stopPropagation()}
        >
          <CircleHelp size={14} />
        </ActionIcon>
      </Tip>
    </Group>
  );
  const editor = (
    <FormLayout>
      {uniques.map((u, i) => (
        <FieldGroup row key={i} data-testid={`unique-row-${i}`}>
          <FormField size="medium">
            <TextInput
              label={t("uniquesPanel.nameLabel")}
              placeholder={t("uniquesPanel.namePlaceholder")}
              value={u.name}
              onChange={(e) => update(i, { name: e.currentTarget.value })}
              data-testid={`unique-name-${i}`}
            />
          </FormField>
          <FormField size="long">
            <MultiSelect
              label={t("uniquesPanel.columnsLabel")}
              placeholder={t("uniquesPanel.columnsPlaceholder")}
              data={columns.map((c) => ({ value: c, label: c }))}
              value={u.columns}
              onChange={(cols) => update(i, { columns: cols })}
              searchable
              data-testid={`unique-columns-${i}`}
            />
          </FormField>
          <ActionIcon
            variant="subtle"
            color="gray"
            aria-label={t("uniquesPanel.removeConstraint")}
            onClick={() => remove(i)}
            data-testid={`unique-remove-${i}`}
          >
            <X size={16} />
          </ActionIcon>
        </FieldGroup>
      ))}
      <FormField size="full">
        <Button
          variant="light"
          size="xs"
          leftSection={<Plus size={14} />}
          onClick={add}
          data-testid="unique-add-button"
        >
          {t("uniquesPanel.addConstraint")}
        </Button>
      </FormField>
    </FormLayout>
  );

  // Flat: the heading and the list, always shown -- on a table's Quality tab, which is its section.
  if (flat)
    return (
      <div data-testid="uniques-panel">
        <div className="uniques-panel__heading">{heading}</div>
        {editor}
      </div>
    );
  return (
    <Accordion
      variant="separated"
      mt="md"
      value={panel}
      onChange={setPanel}
      data-testid="uniques-panel"
    >
      <Accordion.Item value="uniques">
        <Accordion.Control>{heading}</Accordion.Control>
        <Accordion.Panel>{editor}</Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
