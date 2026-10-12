// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1983: how a Qdrant source is reached.

import { Checkbox, PasswordInput, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import type { SourceFormState } from "./SourceFormFields";

interface Props {
  form: SourceFormState;
  setForm: (form: SourceFormState) => void;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function QdrantFields({ form, setForm, fields, setFields }: Props) {
  const { t } = useTranslation();
  return (
    <>
      <FieldGroup>
        <FormField size="long" help={t("qdrantFields.urlHint")}>
          <TextInput
            required
            label={t("qdrantFields.url")}
            placeholder="https://<cluster>.cloud.qdrant.io:6333"
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.currentTarget.value })}
            data-testid="qdrant-url"
          />
        </FormField>
        <FormField size="medium" help={t("qdrantFields.apiKeyHint")}>
          <PasswordInput
            label={t("qdrantFields.apiKey")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.currentTarget.value })}
            data-testid="qdrant-api-key"
          />
        </FormField>
      </FieldGroup>
      <FormField size="medium" help={t("qdrantFields.grpcHint")}>
        <Checkbox
          label={t("qdrantFields.grpc")}
          checked={fields.qdrant_grpc === "true"}
          onChange={(e) =>
            setFields({ ...fields, qdrant_grpc: e.currentTarget.checked ? "true" : "false" })
          }
          data-testid="qdrant-grpc"
        />
      </FormField>
    </>
  );
}
