// Copyright (c) 2026 Kenneth Stott
// Canary: 0bcc0342-1a7f-46ab-b39d-c90e7fccde3a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1954: a ServiceNow source — the instance's address, a username and a password. The
// password may be a ${secret:…} reference.

import { PasswordInput, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { servicenowInstanceUrlValid } from "./servicenow";
import { FieldGroup, FormField } from "../../components/form/FormLayout";

interface ConnectionForm {
  host: string;
  username: string;
  password: string;
}

interface Props<F extends ConnectionForm> {
  form: F;
  setForm: (form: F) => void;
}

export function ServiceNowFields<F extends ConnectionForm>({ form, setForm }: Props<F>) {
  const { t } = useTranslation();
  return (
    <>
      <FormField hint={t("sourceFormFieldsExtended.snInstanceUrlHelp")} size="long">
        <TextInput
          required
          label={t("sourceFormFieldsExtended.snInstanceUrl")}
          value={form.host}
          onChange={(e) => setForm({ ...form, host: e.currentTarget.value })}
          error={
            form.host && !servicenowInstanceUrlValid(form.host)
              ? t("sourceFormFieldsExtended.snInstanceUrlInvalid")
              : undefined
          }
          placeholder="https://acme.service-now.com"
          data-testid="servicenow-instance-url-input"
        />
      </FormField>
      <FieldGroup>
        <FormField size="medium">
          <TextInput
            required
            label={t("sourceFormFieldsExtended.username")}
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.currentTarget.value })}
            data-testid="servicenow-username-input"
          />
        </FormField>
        <FormField size="medium">
          <PasswordInput
            required
            label={t("sourceFormFieldsExtended.password")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.currentTarget.value })}
            data-testid="servicenow-password-input"
          />
        </FormField>
      </FieldGroup>
    </>
  );
}
