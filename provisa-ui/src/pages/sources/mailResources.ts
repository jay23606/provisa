// Copyright (c) 2026 Kenneth Stott
// Canary: 6b2d9e14-3c7a-4f85-a1e0-8d5c2b7f9a36
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1994: what a mail source reads -- mail, calendars, tasks -- as its form holds it. One field,
// `<prefix>_resources`, comma-separated; a new source's form starts on mail, as every source did
// before calendars and tasks were read.

export const MAIL = "mail";
export const CALENDAR = "calendar";
export const TASKS = "tasks";
export const RESOURCES = [MAIL, CALENDAR, TASKS] as const;

/** The resources the form says the source reads, in the server's order. */
export function resourcesOf(fields: Record<string, string>, prefix: string): string[] {
  const held = fields[`${prefix}_resources`];
  // A form that has not said yet is a new source's: it starts on mail.
  const ticked = held === undefined ? [MAIL] : held.split(",").filter(Boolean);
  return RESOURCES.filter((r) => ticked.includes(r));
}

/** The field that holds `resources`. */
export const resourcesField = (prefix: string, resources: string[]) => ({
  [`${prefix}_resources`]: RESOURCES.filter((r) => resources.includes(r)).join(","),
});
