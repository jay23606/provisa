// Copyright (c) 2026 Kenneth Stott
// Canary: 4428a9c1-20e1-48a2-923b-40eb0f0cb5ef
//
// This source code is licensed under the Business Source License 1.1

// REQ-1996: a Logs source's setup -- the files it reads, by a path or a glob, and the format
// their records are in; a regular-expression format names its pattern and, for records that
// span lines, what a record's first line starts with. All of it rides in the source's mapping
// (provisa/logs/settings.py).

import { requestFailed, serverMessage } from "../../i18n/serverMessage";

export const LOGS = "logs";
export const LOGS_REGEX = "regex";

const API_BASE = import.meta.env.VITE_API_BASE || "";

/** A format the server reads, as its catalog lists it. */
export interface LogFormat {
  name: string;
  group: string;
  /** The format is a pattern the source states (the regular expression). */
  pattern: boolean;
}

export interface LogsPreview {
  files: { path: string; bytes: number; modified: string }[];
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
}

/** The row's own columns, which every Logs table has before its format's. */
export const LOGS_OWN_COLUMNS = new Set([
  "_file_id",
  "_file_name",
  "_line_offset",
  "_entry",
  "_raw",
  "_parse_error",
  "_landed_at",
]);

const trimmed = (value: string | undefined) => (value ?? "").trim();

/** The fields still needed before the source can be saved. */
export function logsMissing(fields: Record<string, string>): string[] {
  const missing: string[] = [];
  if (!trimmed(fields.logs_glob)) missing.push("logs_glob");
  if (!trimmed(fields.logs_format)) missing.push("logs_format");
  if (fields.logs_format === LOGS_REGEX && !trimmed(fields.logs_pattern)) {
    missing.push("logs_pattern");
  }
  return missing;
}

/** The source's mapping for what the fields say. */
export function logsMapping(fields: Record<string, string>): Record<string, string> {
  const mapping: Record<string, string> = {
    glob: trimmed(fields.logs_glob),
    format: trimmed(fields.logs_format),
  };
  if (mapping.format === LOGS_REGEX) {
    mapping.pattern = trimmed(fields.logs_pattern);
    const start = trimmed(fields.logs_record_start);
    if (start) mapping.record_start = start;
  }
  return mapping;
}

/** The fields an existing source's mapping fills in. */
export function logsFieldsFromMapping(mappingJson: string): Record<string, string> {
  const mapping = JSON.parse(mappingJson) as Record<string, string>;
  return {
    logs_glob: mapping.glob ?? "",
    logs_format: mapping.format ?? "",
    logs_pattern: mapping.pattern ?? "",
    logs_record_start: mapping.record_start ?? "",
  };
}

async function answered<T>(res: Response, op: string): Promise<T> {
  const said = await res.json();
  if (!res.ok) throw new Error(serverMessage(said, requestFailed(op, res.status)));
  return said as T;
}

/** The formats a Logs source may name. */
export async function fetchLogFormats(): Promise<LogFormat[]> {
  const said = await answered<{ formats: LogFormat[] }>(
    await fetch(`${API_BASE}/admin/logs/formats`),
    "fetchLogFormats",
  );
  return said.formats;
}

/** What the files hold, read as the mapping says: refused by name where they may not be read. */
export async function previewLogs(mapping: Record<string, string>): Promise<LogsPreview> {
  return answered<LogsPreview>(
    await fetch(`${API_BASE}/admin/logs/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mapping }),
    }),
    "previewLogs",
  );
}
