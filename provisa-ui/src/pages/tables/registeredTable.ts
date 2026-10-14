// Copyright (c) 2026 Kenneth Stott
// Canary: 2cdcdaa8-33f4-4690-8f2e-813b2d8e95c9
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import type { MutationResult } from "../../types/admin";

/**
 * The table a registration made, by the id its answer carries (`params.id`): the server may store
 * it under another address than the form sent (an ingest table's schema is the org's control-plane
 * schema). Null when the answer names none -- nothing registered yet, a request queued for approval.
 */
export function registeredTable(result: MutationResult): { id: number } | null {
  const id = result.params?.id;
  return typeof id === "number" ? { id } : null;
}
