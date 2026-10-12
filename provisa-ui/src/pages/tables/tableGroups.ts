// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * A source's tables in the order it lists them, gathered under the heading each is listed under
 * (REQ-1954: a ServiceNow table's theme). Tables without one come first, under no heading.
 */
export function tableGroups<T extends { group?: string | null }>(
  tables: T[],
): [string | null, T[]][] {
  const groups = new Map<string | null, T[]>();
  for (const table of tables) {
    const group = table.group ?? null;
    const members = groups.get(group);
    if (members) members.push(table);
    else groups.set(group, [table]);
  }
  const ungrouped = groups.get(null);
  groups.delete(null);
  return [...(ungrouped ? ([[null, ungrouped]] as [null, T[]][]) : []), ...groups];
}
