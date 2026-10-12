// Copyright (c) 2026 Kenneth Stott
// Canary: 7ceaadf4-d0d8-4f58-9364-8334348aeab2
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The navbar's domain multi-select narrows the Relationships list: a relationship stays when the
// domain of its source table or of its target table is checked -- the domains its row shows. No
// selection, or every domain selected, is no narrowing (as on the Tables page). `narrowTo` holds
// normalized domain ids.
export function relationshipInCheckedDomains(
  narrowTo: ReadonlySet<string> | null,
  source: string | null | undefined,
  target: string | null | undefined,
): boolean {
  if (narrowTo === null) return true;
  return [source, target].some((d) => d != null && narrowTo.has(d));
}
