// Copyright (c) 2026 Kenneth Stott
// Canary: cd9986dc-d2fd-40fd-b774-3a92005900aa
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.

import {
  ActionIcon,
  Badge,
  Checkbox,
  Collapse,
  Group,
  NumberInput,
  Select,
  TagsInput,
  Text,
} from "@mantine/core";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil } from "lucide-react";
import type { RegisteredTable } from "../../types/admin";
import { useCalendars } from "../../hooks/useAdminQueries";
import type { CalendarSummary } from "../../hooks/useAdminQueries";
import { CalendarCreateModal } from "./CalendarCreateModal";
import { FieldLabel } from "./FieldLabel";
import { RecurrenceBuilder } from "./RecurrenceBuilder";
import { FieldGroup, FormChecks, FormField, FormLayout } from "../../components/form/FormLayout";

// REQ-962/1168/1169: the collapsible Snapshot Schedule panel — the calendar picker, the recurrence
// grain (nesting preset or a custom Outlook/iCalendar RRULE via RecurrenceBuilder), allowed-lateness,
// the business-day existence gate, and the REQ-961 preflight fresh-input set. Owns its own open state
// and the calendar registry, which nothing outside the panel consumes.
export function SnapshotSchedulePanel({
  editingTable,
  setEditingTable,
}: {
  editingTable: RegisteredTable;
  setEditingTable: (t: RegisteredTable) => void;
}) {
  const { t } = useTranslation();
  const { calendars, refetch: refetchCalendars } = useCalendars();
  const [snapshotOpen, setSnapshotOpen] = useState(
    Boolean(editingTable.mvCalendar), // open the panel when a schedule is already configured
  );
  const [calendarModalOpen, setCalendarModalOpen] = useState(false);
  const [editingCalendar, setEditingCalendar] = useState<CalendarSummary | null>(null);

  return (
    <FormField size="full">
      <div>
        <Group
          gap="xs"
          wrap="nowrap"
          style={{ cursor: "pointer" }}
          onClick={() => setSnapshotOpen((o) => !o)}
          data-testid="mv-snapshot-panel-toggle"
          role="button"
          aria-expanded={snapshotOpen}
        >
          <ActionIcon variant="subtle" size="sm" aria-hidden>
            {snapshotOpen ? "−" : "+"}
          </ActionIcon>
          <Text fw={600} size="sm">
            {t("tableEditForm.snapshotPanel")}
          </Text>
          {editingTable.mvCalendar && (
            <Badge size="xs" variant="light" color="grape">
              {editingTable.mvCalendar}
              {/* display-only relabel of the RFC 5545 prefix; the stored value stays RRULE: */}
              {editingTable.mvGrain
                ? ` · ${editingTable.mvGrain.replace(/^RRULE:/i, "RECURS:")}`
                : ""}
            </Badge>
          )}
        </Group>
        <Collapse in={snapshotOpen}>
          <FormLayout style={{ paddingTop: "var(--mantine-spacing-xs)" }}>
            <FieldGroup style={{ alignItems: "flex-end" }}>
              <FormField help={t("tableEditForm.calendarHelp")} size="medium">
                <Select
                  label={t("tableEditForm.calendarLabel")}
                  data-testid="mv-calendar"
                  placeholder={
                    calendars.length
                      ? t("tableEditForm.calendarPlaceholder")
                      : t("tableEditForm.calendarPlaceholderEmpty")
                  }
                  data={calendars.map((c) => ({
                    value: c.name,
                    label: `${c.name} (v${c.version}, ${c.baseSystem}, ${c.tz})`,
                  }))}
                  value={editingTable.mvCalendar}
                  onChange={(v) => setEditingTable({ ...editingTable, mvCalendar: v || null })}
                  comboboxProps={{ withinPortal: true }}
                  clearable
                />
              </FormField>
              <ActionIcon
                variant="light"
                size="lg"
                aria-label={t("tableEditForm.calendarNewAria")}
                data-testid="mv-calendar-new"
                onClick={() => {
                  setEditingCalendar(null);
                  setCalendarModalOpen(true);
                }}
              >
                +
              </ActionIcon>
              {editingTable.mvCalendar && (
                <ActionIcon
                  variant="light"
                  size="lg"
                  aria-label={t("tableEditForm.calEditCalendarAria")}
                  data-testid="mv-calendar-edit"
                  onClick={() => {
                    // the picker binds by name; the query returns newest-version-first, so the first
                    // match is the latest version to revise in place.
                    setEditingCalendar(
                      calendars.find((c) => c.name === editingTable.mvCalendar) ?? null,
                    );
                    setCalendarModalOpen(true);
                  }}
                >
                  <Pencil size={16} />
                </ActionIcon>
              )}
            </FieldGroup>
            {editingTable.mvCalendar && (
              <RecurrenceBuilder
                label={
                  <FieldLabel
                    text={t("tableEditForm.grainLabel")}
                    help={t("tableEditForm.grainHelp")}
                  />
                }
                testId="mv-grain"
                placeholder={t("tableEditForm.grainPlaceholder")}
                value={editingTable.mvGrain}
                onChange={(v) => setEditingTable({ ...editingTable, mvGrain: v })}
              />
            )}
            {editingTable.mvCalendar && (
              <FormField help={t("tableEditForm.allowedLatenessHelp")} size="short">
                <NumberInput
                  label={t("tableEditForm.allowedLatenessLabel")}
                  data-testid="mv-allowed-lateness"
                  min={0}
                  step={60}
                  value={editingTable.mvAllowedLateness}
                  onChange={(v) =>
                    setEditingTable({
                      ...editingTable,
                      mvAllowedLateness: typeof v === "number" ? v : parseFloat(String(v)) || 0,
                    })
                  }
                />
              </FormField>
            )}
            <FormChecks>
              {editingTable.mvCalendar && (
                <FormField size="short">
                  <Checkbox
                    data-testid="mv-business-day-grain"
                    checked={editingTable.mvBusinessDayGrain}
                    onChange={(e) =>
                      setEditingTable({
                        ...editingTable,
                        mvBusinessDayGrain: e.currentTarget.checked,
                      })
                    }
                    label={t("tableEditForm.businessDayGrainLabel")}
                  />
                </FormField>
              )}
              {editingTable.mvCalendar && (
                <FormField help={t("tableEditForm.expectedAllHelp")} size="short">
                  <Checkbox
                    data-testid="mv-expected-all"
                    checked={editingTable.mvExpectedEvents === null}
                    onChange={(e) =>
                      setEditingTable({
                        ...editingTable,
                        // null = verify every lineage input (default); [] = a custom set (verify
                        // nothing until inputs are named) — REQ-961 preflight contract.
                        mvExpectedEvents: e.currentTarget.checked ? null : [],
                      })
                    }
                    label={t("tableEditForm.expectedAllLabel")}
                  />
                </FormField>
              )}
            </FormChecks>
            {editingTable.mvCalendar && editingTable.mvExpectedEvents !== null && (
              <FormField size="long">
                <TagsInput
                  label={t("tableEditForm.expectedEventsLabel")}
                  data-testid="mv-expected-events"
                  placeholder={t("tableEditForm.expectedEventsPlaceholder")}
                  value={editingTable.mvExpectedEvents ?? []}
                  onChange={(v) => setEditingTable({ ...editingTable, mvExpectedEvents: v })}
                  comboboxProps={{ withinPortal: true }}
                  clearable
                />
              </FormField>
            )}
          </FormLayout>
        </Collapse>
        <CalendarCreateModal
          key={editingCalendar ? `edit-${editingCalendar.name}-${editingCalendar.version}` : "new"}
          opened={calendarModalOpen}
          onClose={() => setCalendarModalOpen(false)}
          editCalendar={editingCalendar}
          onCreated={(nm) => {
            refetchCalendars();
            setEditingTable({ ...editingTable, mvCalendar: nm });
          }}
          onDeleted={(nm) => {
            refetchCalendars();
            if (editingTable.mvCalendar === nm) {
              setEditingTable({ ...editingTable, mvCalendar: null });
            }
          }}
        />
      </div>
    </FormField>
  );
}
