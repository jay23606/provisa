// Copyright (c) 2026 Kenneth Stott
// Canary: f38a8d39-6a83-49c6-be91-f127a3a1d601
//
// This source code is licensed under the Business Source License 1.1

// REQ-1996: a Logs source -- the files it reads and the format their records are in, and what
// they hold before it is saved: the files the glob matches, the columns the format gives, and
// the first rows as they would land.

import { useEffect, useState } from "react";
import { Alert, Button, ScrollArea, Select, Table, Text, TextInput } from "@mantine/core";
import { Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import {
  LOGS_OWN_COLUMNS,
  LOGS_REGEX,
  fetchLogFormats,
  logsMapping,
  logsMissing,
  previewLogs,
  type LogFormat,
  type LogsPreview,
} from "./logs";

interface Props {
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

function shown(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** A short value on one line; a long one (a message, a stack trace) as written. */
function cellStyle(text: string) {
  const long = text.length > 40 || text.includes("\n");
  return { maxWidth: 360, whiteSpace: long ? ("pre-wrap" as const) : ("nowrap" as const) };
}

export function LogsFields({ fields, setFields }: Props) {
  const { t } = useTranslation();
  const [formats, setFormats] = useState<LogFormat[] | null>(null);
  const [formatsError, setFormatsError] = useState<string | null>(null);
  const [preview, setPreview] = useState<LogsPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const missing = new Set(logsMissing(fields));
  const set = (key: string, value: string) => {
    setPreview(null);
    setPreviewError(null);
    setFields({ ...fields, [key]: value });
  };

  useEffect(() => {
    let live = true;
    fetchLogFormats().then(
      (found) => live && setFormats(found),
      (failed: Error) => live && setFormatsError(failed.message),
    );
    return () => {
      live = false;
    };
  }, []);

  // The formats in their groups, as the server lists them; each named in the reader's language.
  const groups: { group: string; items: { value: string; label: string }[] }[] = [];
  for (const format of formats ?? []) {
    const label = t(`logsFields.group.${format.group}`);
    let group = groups.find((g) => g.group === label);
    if (!group) {
      group = { group: label, items: [] };
      groups.push(group);
    }
    group.items.push({ value: format.name, label: t(`logsFields.formats.${format.name}`) });
  }

  const read = async () => {
    setReading(true);
    setPreviewError(null);
    try {
      setPreview(await previewLogs(logsMapping(fields)));
    } catch (failed) {
      setPreview(null);
      setPreviewError((failed as Error).message);
    } finally {
      setReading(false);
    }
  };

  const formatColumns = (preview?.columns ?? []).filter((c) => !LOGS_OWN_COLUMNS.has(c.name));
  const regex = fields.logs_format === LOGS_REGEX;
  return (
    <>
      <FieldGroup>
        <FormField size="long" help={t("logsFields.globHelp")}>
          <TextInput
            required
            label={t("logsFields.glob")}
            placeholder="/var/log/system.log*"
            value={fields.logs_glob ?? ""}
            onChange={(e) => set("logs_glob", e.currentTarget.value)}
            data-testid="logs-glob"
          />
        </FormField>
        <FormField size="medium" help={t("logsFields.formatHelp")}>
          <Select
            required
            label={t("logsFields.format")}
            placeholder={
              formats === null && !formatsError ? t("logsFields.loadingFormats") : undefined
            }
            data={groups}
            value={fields.logs_format || null}
            onChange={(v) => set("logs_format", v ?? "")}
            searchable
            allowDeselect={false}
            error={formatsError ?? undefined}
            data-testid="logs-format"
          />
        </FormField>
      </FieldGroup>
      {regex && (
        <FieldGroup>
          <FormField size="long" hint={t("logsFields.patternHint")}>
            <TextInput
              required
              label={t("logsFields.pattern")}
              placeholder="(?P<level>[A-Z]+) (?P<message>.*)"
              value={fields.logs_pattern ?? ""}
              onChange={(e) => set("logs_pattern", e.currentTarget.value)}
              styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }}
              data-testid="logs-pattern"
            />
          </FormField>
          <FormField size="long" help={t("logsFields.recordStartHelp")}>
            <TextInput
              label={t("logsFields.recordStart")}
              placeholder="\d{4}-\d{2}-\d{2} "
              value={fields.logs_record_start ?? ""}
              onChange={(e) => set("logs_record_start", e.currentTarget.value)}
              styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }}
              data-testid="logs-record-start"
            />
          </FormField>
        </FieldGroup>
      )}
      <FieldGroup>
        <Button
          variant="light"
          leftSection={<Eye size={14} />}
          loading={reading}
          disabled={missing.size > 0}
          onClick={read}
          data-testid="logs-preview"
        >
          {t("logsFields.preview")}
        </Button>
      </FieldGroup>
      {previewError && (
        <Alert color="red" data-testid="logs-preview-error">
          {previewError}
        </Alert>
      )}
      {preview && (
        <div data-testid="logs-preview-result" style={{ minWidth: 0, maxWidth: "100%" }}>
          <Text size="sm" fw={500}>
            {t("logsFields.filesFound", { count: preview.files.length })}
          </Text>
          {preview.files.map((file) => (
            <Text key={file.path} size="sm" ff="monospace">
              {file.path}
            </Text>
          ))}
          <Text size="sm" fw={500} mt="sm">
            {t("logsFields.columns")}
          </Text>
          <Text size="sm" ff="monospace">
            {formatColumns.map((c) => `${c.name} ${c.type}`).join(", ")}
          </Text>
          <Text size="sm" fw={500} mt="sm">
            {t("logsFields.firstRows", { count: preview.rows.length })}
          </Text>
          <ScrollArea type="auto" style={{ maxWidth: "100%" }}>
            <Table striped withTableBorder fz="xs" data-testid="logs-preview-rows">
              <Table.Thead>
                <Table.Tr>
                  {formatColumns.map((c) => (
                    <Table.Th key={c.name}>{c.name}</Table.Th>
                  ))}
                  <Table.Th>{t("logsFields.parseError")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {preview.rows.map((row) => (
                  <Table.Tr key={`${shown(row._file_id)}:${shown(row._line_offset)}`}>
                    {formatColumns.map((c) => (
                      <Table.Td key={c.name} style={cellStyle(shown(row[c.name]))}>
                        {shown(row[c.name])}
                      </Table.Td>
                    ))}
                    <Table.Td style={{ maxWidth: 360 }}>{shown(row._parse_error)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </div>
      )}
    </>
  );
}
