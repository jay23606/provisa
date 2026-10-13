// Copyright (c) 2026 Kenneth Stott
// Canary: 597c8b22-acd3-4181-9a70-08fbff05916f
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { createContext, useContext } from "react";
import type { ExampleQuery } from "../api/setup";

/** REQ-2009: the named demo's example GraphQL queries, from /setup/status (App.tsx provides them).
 * A page rendered outside the app (a component test) has read no status: no demo ships it any. */
export const ExampleQueriesContext = createContext<ExampleQuery[]>([]);

export function useExampleQueries(): ExampleQuery[] {
  return useContext(ExampleQueriesContext);
}
