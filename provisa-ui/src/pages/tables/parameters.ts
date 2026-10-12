// Copyright (c) 2026 Kenneth Stott
// Canary: b83f5d45-6110-4a64-8604-ad80a08690b8
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1986: a table's parameters, as provisa/core/parameters.py has them.

import type { TableColumn } from "../../types/admin";

const NF_PREFIX = "_nf_";

/** The parameter as a caller names it: its column's name without the `_nf_` prefix. */
export function parameterName(columnName: string): string {
  return columnName.startsWith(NF_PREFIX) ? columnName.slice(NF_PREFIX.length) : columnName;
}

/** Whether a read of the table must give the parameter a value: the source or a steward
 * requires it. */
export function isRequired(c: Pick<TableColumn, "nativeFilterRequired" | "requiredBySteward">) {
  return Boolean(c.nativeFilterRequired) || Boolean(c.requiredBySteward);
}
