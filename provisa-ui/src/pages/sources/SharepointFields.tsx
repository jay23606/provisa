// Copyright (c) 2026 Kenneth Stott
// Canary: 8b7e3180-4070-423d-97b3-45f00ef5e7cd
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The SharePoint connection fields of the source form.

import { PasswordInput, Select, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import type { SourceFormFieldsProps } from "./SourceFormFields";

export function SharepointFields({
  form,
  setForm,
  spAuthType,
  setSpAuthType,
  spCertPath,
  setSpCertPath,
  spCertPassword,
  setSpCertPassword,
  spUsername,
  setSpUsername,
  spPassword,
  setSpPassword,
}: Pick<
  SourceFormFieldsProps,
  | "form"
  | "setForm"
  | "spAuthType"
  | "setSpAuthType"
  | "spCertPath"
  | "setSpCertPath"
  | "spCertPassword"
  | "setSpCertPassword"
  | "spUsername"
  | "setSpUsername"
  | "spPassword"
  | "setSpPassword"
>) {
  const { t } = useTranslation();
  return (
    <>
      <FormField size="long">
        <TextInput
          required
          label={t("sourceFormFieldsExtended.siteUrl")}
          value={form.host}
          onChange={(e) => setForm({ ...form, host: e.target.value })}
          placeholder="https://contoso.sharepoint.com/sites/mysite"
          data-testid="sharepoint-site-url-input"
        />
      </FormField>
      <FormField size="medium">
        <TextInput
          required
          label={t("sourceFormFieldsExtended.tenantId")}
          value={form.database}
          onChange={(e) => setForm({ ...form, database: e.target.value })}
          placeholder={t("sourceFormFieldsExtended.tenantIdPlaceholder")}
          data-testid="sharepoint-tenant-id-input"
        />
      </FormField>
      <FormField size="medium">
        <Select
          label={t("sourceFormFieldsExtended.authType")}
          value={spAuthType}
          onChange={(v) => setSpAuthType(v ?? "")}
          data={[
            {
              value: "CLIENT_CREDENTIALS",
              label: t("sourceFormFieldsExtended.clientCredentials"),
            },
            {
              value: "USERNAME_PASSWORD",
              label: t("sourceFormFieldsExtended.usernamePassword"),
            },
            { value: "CERTIFICATE", label: t("sourceFormFieldsExtended.certificate") },
          ]}
          allowDeselect={false}
          data-testid="sharepoint-auth-type-select"
        />
      </FormField>
      <FormField size="medium">
        <TextInput
          required
          label={t("sourceFormFieldsExtended.clientId")}
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          placeholder={t("sourceFormFieldsExtended.clientIdPlaceholder")}
          data-testid="sharepoint-client-id-input"
        />
      </FormField>
      {spAuthType === "CLIENT_CREDENTIALS" && (
        <FormField size="medium">
          <PasswordInput
            label={t("sourceFormFieldsExtended.clientSecret")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder={t("sourceFormFieldsExtended.clientSecretPlaceholder")}
            data-testid="sharepoint-client-secret-input"
          />
        </FormField>
      )}
      {spAuthType === "USERNAME_PASSWORD" && (
        <>
          <FieldGroup>
            <FormField size="medium">
              <TextInput
                required
                label={t("sourceFormFieldsExtended.spUsername")}
                value={spUsername}
                onChange={(e) => setSpUsername(e.target.value)}
                placeholder="user@contoso.com"
                data-testid="sharepoint-sp-username-input"
              />
            </FormField>
            <FormField size="medium">
              <PasswordInput
                required
                label={t("sourceFormFieldsExtended.spPassword")}
                value={spPassword}
                onChange={(e) => setSpPassword(e.target.value)}
                data-testid="sharepoint-sp-password-input"
              />
            </FormField>
          </FieldGroup>
        </>
      )}
      {spAuthType === "CERTIFICATE" && (
        <>
          <FormField size="medium">
            <PasswordInput
              label={t("sourceFormFieldsExtended.clientSecret")}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder={t("sourceFormFieldsExtended.clientSecretCertPlaceholder")}
              data-testid="sharepoint-cert-client-secret-input"
            />
          </FormField>
          <FormField size="long">
            <TextInput
              required
              label={t("sourceFormFieldsExtended.certificatePath")}
              value={spCertPath}
              onChange={(e) => setSpCertPath(e.target.value)}
              placeholder="/certs/sharepoint.pfx"
              data-testid="sharepoint-cert-path-input"
            />
          </FormField>
          <FormField size="medium">
            <PasswordInput
              label={t("sourceFormFieldsExtended.certificatePassword")}
              value={spCertPassword}
              onChange={(e) => setSpCertPassword(e.target.value)}
              data-testid="sharepoint-cert-password-input"
            />
          </FormField>
        </>
      )}
    </>
  );
}
