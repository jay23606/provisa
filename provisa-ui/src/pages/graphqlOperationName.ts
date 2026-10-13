// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/** The name of a GraphQL document's first named operation, read as GraphiQL reads it for a tab's
 * title (a line that is not a comment, naming a query, mutation or subscription); null for an
 * anonymous one. */
export function operationNameOf(query: string): string | null {
  const named =
    /^(?!\s*#)[^\n]*?\b(?:query|mutation|subscription)\s+([_A-Za-z][_0-9A-Za-z]*)/m.exec(query);
  return named ? named[1] : null;
}
