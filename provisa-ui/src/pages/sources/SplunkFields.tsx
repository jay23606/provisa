// Copyright (c) 2026 Kenneth Stott
// Canary: e7690c8e-b6f3-4e5d-8860-b9c3ff75d474
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The Splunk connection fields of the source form.

import { Checkbox, NumberInput, PasswordInput, Select, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormChecks, FormField } from "../../components/form/FormLayout";
import type { SourceFormFieldsProps } from "./SourceFormFields";

export function SplunkFields({
  form,
  setForm,
  splunkDisableSsl,
  splunkAuthMode,
  setSplunkAuthMode,
  setSplunkDisableSsl,
}: Pick<
  SourceFormFieldsProps,
  | "form"
  | "setForm"
  | "splunkDisableSsl"
  | "splunkAuthMode"
  | "setSplunkAuthMode"
  | "setSplunkDisableSsl"
>) {
  const { t } = useTranslation();
  return (
    <>
      <FieldGroup>
        <FormField size="medium">
          <TextInput
            required
            label={t("sourceFormFieldsExtended.host")}
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.target.value })}
            placeholder="splunk.example.com"
            data-testid="splunk-host-input"
          />
        </FormField>
        <FormField size="short">
          <NumberInput
            label={t("sourceFormFieldsExtended.port")}
            value={form.port}
            onChange={(v) => setForm({ ...form, port: Number(v) || 0 })}
            data-testid="splunk-port-input"
          />
        </FormField>
      </FieldGroup>
      <FormField size="medium">
        <Select
          label={t("sourceFormFieldsExtended.authMethod")}
          value={splunkAuthMode}
          onChange={(v) => setSplunkAuthMode(v === "userpass" ? "userpass" : "token")}
          data={[
            { value: "token", label: t("sourceFormFieldsExtended.token") },
            { value: "userpass", label: t("sourceFormFieldsExtended.usernamePassword") },
          ]}
          allowDeselect={false}
          data-testid="splunk-auth-mode-select"
        />
      </FormField>
      {splunkAuthMode === "token" ? (
        <FormField size="long">
          <PasswordInput
            required
            label={t("sourceFormFieldsExtended.authToken")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder={t("sourceFormFieldsExtended.authToken")}
            data-testid="splunk-auth-token-input"
          />
        </FormField>
      ) : (
        <>
          <FieldGroup>
            <FormField size="medium">
              <TextInput
                required
                label={t("sourceFormFieldsExtended.username")}
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                data-testid="splunk-username-input"
              />
            </FormField>
            <FormField size="medium">
              <PasswordInput
                required
                label={t("sourceFormFieldsExtended.password")}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                data-testid="splunk-password-input"
              />
            </FormField>
          </FieldGroup>
        </>
      )}
      <FormField size="medium">
        <TextInput
          label={t("sourceFormFieldsExtended.appOptional")}
          value={form.database}
          onChange={(e) => setForm({ ...form, database: e.target.value })}
          placeholder="Splunk_SA_CIM"
          data-testid="splunk-app-input"
        />
      </FormField>
      <FormChecks>
        <FormField size="short">
          <Checkbox
            label={t("sourceFormFieldsExtended.disableSslValidation")}
            checked={splunkDisableSsl}
            onChange={(e) => setSplunkDisableSsl(e.currentTarget.checked)}
            data-testid="splunk-disable-ssl-checkbox"
          />
        </FormField>
      </FormChecks>
    </>
  );
}
