// Copyright (c) 2026 Kenneth Stott
// Canary: 9ccc28d4-d586-4912-b590-fff8123c2b38
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.

import { LabelWithHelp } from "../../components/form/FormLayout";

// A form-field label with an inline ⓘ help tooltip, shared across the table-edit form and its
// extracted panels. ``required`` renders the asterisk inline (so it stays on the label row rather
// than the input's own, which would sit apart from a custom label node).
export function FieldLabel({
  text,
  help,
  required = false,
  textId,
}: {
  text: string;
  help: string;
  required?: boolean;
  /** From useHelpNaming, when the control is to be named by the text alone. */
  textId?: string;
}) {
  return (
    <span className="form-label-standalone">
      <LabelWithHelp label={text} help={help} required={required} textId={textId} />
    </span>
  );
}
