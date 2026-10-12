// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Fragment, type ReactNode } from "react";
import { Text } from "@mantine/core";

/** One read-only field of a table's detail: its label and its value as text. */
export interface DetailField {
  label: string;
  value: ReactNode;
  testId?: string;
}

/**
 * A section's fields read-only, label beside value, in the order the edit form has them. A field
 * with no value says so in the value; it is not left out, so the read view and the form list the
 * same fields.
 */
export function DetailFields({ fields, testId }: { fields: DetailField[]; testId?: string }) {
  return (
    <dl className="detail-fields" data-testid={testId}>
      {fields.map((f) => (
        <Fragment key={f.label}>
          <Text component="dt" c="dimmed" fw={500} size="sm">
            {f.label}
          </Text>
          <Text component="dd" m={0} size="sm" data-testid={f.testId}>
            {f.value}
          </Text>
        </Fragment>
      ))}
    </dl>
  );
}
