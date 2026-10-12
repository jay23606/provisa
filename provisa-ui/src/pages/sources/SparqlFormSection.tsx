// Copyright (c) 2026 Kenneth Stott
// Canary: 36804607-69cb-401c-9078-173be064f6c7
// Canary: placeholder
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Extracted out of SourceFormFieldsExtended.tsx to keep that file under the eslint max-lines gate
// (same pattern as PushFeedFormSection.tsx).

import { PasswordInput, Select, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { AuthUserPass } from "./AuthUserPass";
import type { SourceFormState } from "./SourceFormFields";
import { FormField } from "../../components/form/FormLayout";

export function SparqlFormSection({
  form,
  setForm,
  authType,
  setAuthType,
  authFields,
  setAuthFields,
}: {
  form: SourceFormState;
  setForm: (f: SourceFormState) => void;
  authType: string;
  setAuthType: (v: string) => void;
  authFields: Record<string, string>;
  setAuthFields: (f: Record<string, string>) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <FormField size="long">
        <TextInput
          required
          label={t("sourceFormFieldsExtended.endpointUrl")}
          value={form.host}
          onChange={(e) => setForm({ ...form, host: e.target.value })}
          placeholder="https://dbpedia.org/sparql"
          data-testid="sparql-endpoint-input"
        />
      </FormField>
      {/* REQ-1740: optional named-graph restriction, rides in federation_hints. */}
      <FormField size="long">
        <TextInput
          label={t("sourceFormFieldsExtended.defaultGraphUri")}
          value={authFields.default_graph_uri ?? ""}
          onChange={(e) => setAuthFields({ ...authFields, default_graph_uri: e.target.value })}
          placeholder="http://example.org/graph (optional)"
          data-testid="sparql-default-graph-uri-input"
        />
      </FormField>
      <FormField size="medium">
        <Select
          label={t("sourceFormFieldsExtended.authentication")}
          value={authType}
          onChange={(v) => {
            setAuthType(v ?? "");
            // Keep default_graph_uri — it's orthogonal to auth mode.
            setAuthFields({ default_graph_uri: authFields.default_graph_uri ?? "" });
          }}
          data={[
            { value: "none", label: t("sourceFormFieldsExtended.authNone") },
            { value: "bearer", label: t("sourceFormFieldsExtended.authBearer") },
            { value: "basic", label: t("sourceFormFieldsExtended.authBasic") },
          ]}
          allowDeselect={false}
          data-testid="sparql-auth-type-select"
        />
      </FormField>
      {authType === "bearer" && (
        <FormField size="long">
          <PasswordInput
            required
            label={t("sourceFormFieldsExtended.token")}
            value={authFields.token ?? ""}
            onChange={(e) => setAuthFields({ ...authFields, token: e.target.value })}
            placeholder="${env:SPARQL_TOKEN}"
            data-testid="sparql-token-input"
          />
        </FormField>
      )}
      {authType === "basic" && (
        <AuthUserPass authFields={authFields} setAuthFields={setAuthFields} />
      )}
    </>
  );
}
