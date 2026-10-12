// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1981: an Amazon Athena source — its region and Glue database, where Athena writes its
// results, an access key pair (or none, for the AWS credential chain) and an optional role.

import { PasswordInput, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { athenaResultLocationValid } from "./athena";
import { FieldGroup, FormField } from "../../components/form/FormLayout";

interface ConnectionForm {
  database: string;
  username: string;
  password: string;
}

export function AthenaFields<F extends ConnectionForm>({
  form,
  setForm,
  fields,
  setFields,
}: {
  form: F;
  setForm: (form: F) => void;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}) {
  const { t } = useTranslation();
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFields({ ...fields, [key]: e.currentTarget.value });
  const location = fields.s3_staging_dir ?? "";
  return (
    <>
      <FieldGroup>
        <FormField size="short">
          <TextInput
            required
            label={t("athenaFields.region")}
            value={fields.region ?? ""}
            onChange={set("region")}
            placeholder="us-east-1"
            data-testid="athena-region-input"
          />
        </FormField>
        <FormField size="medium">
          <TextInput
            required
            label={t("athenaFields.database")}
            value={form.database}
            onChange={(e) => setForm({ ...form, database: e.currentTarget.value })}
            placeholder="sales"
            data-testid="athena-database-input"
          />
        </FormField>
      </FieldGroup>
      <FieldGroup>
        <FormField size="medium" hint={t("athenaFields.workgroupHint")}>
          <TextInput
            label={t("athenaFields.workgroup")}
            value={fields.workgroup ?? ""}
            onChange={set("workgroup")}
            placeholder="primary"
            data-testid="athena-workgroup-input"
          />
        </FormField>
        <FormField size="medium" hint={t("athenaFields.catalogHint")}>
          <TextInput
            label={t("athenaFields.catalog")}
            value={fields.catalog ?? ""}
            onChange={set("catalog")}
            placeholder="AwsDataCatalog"
            data-testid="athena-catalog-input"
          />
        </FormField>
      </FieldGroup>
      <FormField size="long" hint={t("athenaFields.resultLocationHint")}>
        <TextInput
          label={t("athenaFields.resultLocation")}
          value={location}
          onChange={set("s3_staging_dir")}
          error={
            athenaResultLocationValid(location)
              ? undefined
              : t("athenaFields.resultLocationInvalid")
          }
          placeholder="s3://my-bucket/athena-results/"
          data-testid="athena-result-location-input"
        />
      </FormField>
      <FieldGroup>
        <FormField size="medium" hint={t("athenaFields.accessKeyHint")}>
          <TextInput
            label={t("athenaFields.accessKeyId")}
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.currentTarget.value })}
            data-testid="athena-access-key-input"
          />
        </FormField>
        <FormField size="medium">
          <PasswordInput
            label={t("athenaFields.secretAccessKey")}
            required={!!form.username}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.currentTarget.value })}
            data-testid="athena-secret-key-input"
          />
        </FormField>
      </FieldGroup>
      <FormField size="long" hint={t("athenaFields.roleArnHint")}>
        <TextInput
          label={t("athenaFields.roleArn")}
          value={fields.role_arn ?? ""}
          onChange={set("role_arn")}
          placeholder="arn:aws:iam::123456789012:role/athena-reader"
          data-testid="athena-role-arn-input"
        />
      </FormField>
    </>
  );
}
