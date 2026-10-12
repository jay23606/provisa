// Copyright (c) 2026 Kenneth Stott
// Canary: 5d66fccb-8fcd-4f8d-b63e-618e7711797f
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1982: how an Azure Cosmos DB for NoSQL source is reached and signed in to.

import { PasswordInput, Select, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import { COSMOS_ENTRA, COSMOS_KEY } from "./cosmosdb";
import type { SourceFormState } from "./SourceFormFields";

interface Props {
  form: SourceFormState;
  setForm: (form: SourceFormState) => void;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function CosmosDbFields({ form, setForm, fields, setFields }: Props) {
  const { t } = useTranslation();
  const entra = (fields.cosmos_auth ?? COSMOS_KEY) === COSMOS_ENTRA;
  const set = (key: string, value: string) => setFields({ ...fields, [key]: value });
  return (
    <>
      <FieldGroup>
        <FormField size="long" hint={t("cosmosDbFields.endpointHint")}>
          <TextInput
            required
            label={t("cosmosDbFields.endpoint")}
            placeholder="https://<account>.documents.azure.com:443/"
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.currentTarget.value })}
            data-testid="cosmosdb-endpoint"
          />
        </FormField>
        <FormField size="medium">
          <TextInput
            required
            label={t("cosmosDbFields.database")}
            value={form.database}
            onChange={(e) => setForm({ ...form, database: e.currentTarget.value })}
            data-testid="cosmosdb-database"
          />
        </FormField>
      </FieldGroup>
      <FieldGroup>
        <FormField section="authentication" size="medium">
          <Select
            label={t("cosmosDbFields.auth")}
            data={[
              { value: COSMOS_KEY, label: t("cosmosDbFields.authKey") },
              { value: COSMOS_ENTRA, label: t("cosmosDbFields.authEntra") },
            ]}
            value={entra ? COSMOS_ENTRA : COSMOS_KEY}
            allowDeselect={false}
            onChange={(v) => v && set("cosmos_auth", v)}
            data-testid="cosmosdb-auth"
          />
        </FormField>
        <FormField size="medium" hint={t("cosmosDbFields.secretHint")}>
          <PasswordInput
            required
            label={t(entra ? "cosmosDbFields.clientSecret" : "cosmosDbFields.accountKey")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.currentTarget.value })}
            data-testid="cosmosdb-secret"
          />
        </FormField>
      </FieldGroup>
      {entra && (
        <FieldGroup>
          <FormField section="authentication" size="medium">
            <TextInput
              required
              label={t("cosmosDbFields.tenantId")}
              value={fields.cosmos_tenant_id ?? ""}
              onChange={(e) => set("cosmos_tenant_id", e.currentTarget.value)}
              data-testid="cosmosdb-tenant-id"
            />
          </FormField>
          <FormField section="authentication" size="medium">
            <TextInput
              required
              label={t("cosmosDbFields.clientId")}
              value={fields.cosmos_client_id ?? ""}
              onChange={(e) => set("cosmos_client_id", e.currentTarget.value)}
              data-testid="cosmosdb-client-id"
            />
          </FormField>
        </FieldGroup>
      )}
    </>
  );
}
