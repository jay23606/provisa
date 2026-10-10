// Copyright (c) 2026 Kenneth Stott
// Canary: b25ffbee-f62f-458f-a06f-2aaff451cddb
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The one date a mail source may state: nothing received before it is held (`mail_since`).
// Google Workspace and Microsoft 365 sources state it alike, so both forms show this field
// with the same label and hint.

import { TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormField } from "../../components/form/FormLayout";

interface MailSinceFieldProps {
  value: string;
  onChange: (value: string) => void;
  testId: string;
}

export function MailSinceField({ value, onChange, testId }: MailSinceFieldProps) {
  const { t } = useTranslation();
  return (
    <FormField hint={t("sourceFormFields.mailSinceHelp")} size="short">
      <TextInput
        type="date"
        label={t("sourceFormFields.mailSince")}
        value={value}
        onChange={(e) => onChange(e.currentTarget.value)}
        data-testid={testId}
      />
    </FormField>
  );
}
