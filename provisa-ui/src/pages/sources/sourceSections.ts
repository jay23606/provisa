// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * A source's details, in sections: the same tabs in its read view and its edit form. Connection,
 * Authentication and Load are its form's fields; Tables lists the tables registered from it;
 * Operations its commands and APIs, for the kinds of source that have them.
 */
export type SourceSection = "connection" | "authentication" | "load" | "tables" | "operations";
export const SOURCE_SECTIONS: SourceSection[] = [
  "connection",
  "authentication",
  "load",
  "tables",
  "operations",
];

/** The form's sections: its fields are in one of these, the first unless marked otherwise. */
export const FORM_SECTIONS: SourceSection[] = ["connection", "authentication", "load"];

/** The kinds of source whose operations (commands, APIs) are their own: they have Operations. */
export const OPERATIONS_TYPES: ReadonlySet<string> = new Set([
  "servicenow",
  "openapi",
  "graphql_remote",
]);

/** The sections a source of ``type`` shows: a form section only when the form has fields in it
 *  for that type (``formSections``), Tables always, Operations for the kinds that have them. */
export function shownSourceSections(type: string, formSections: string[]): SourceSection[] {
  return SOURCE_SECTIONS.filter((s) =>
    s === "tables"
      ? true
      : s === "operations"
        ? OPERATIONS_TYPES.has(type)
        : formSections.includes(s),
  );
}
