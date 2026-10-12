// Copyright (c) 2026 Kenneth Stott
// Canary: 1b4b1533-e005-4540-9c4d-cb1e4bf974f1
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-990: the credentials of the object store a CSV/Parquet file is in, shown for the store its
// path names (s3://, gs://, an Azure URL). Each value may be a ${secret:…} reference resolved from
// the org's vault, as every source credential may.

import { PasswordInput, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import type { ObjectStore } from "./objectStoreHints";
import { FieldGroup, FormField } from "../../components/form/FormLayout";

interface Props {
  store: ObjectStore;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function ObjectStoreCredentialFields({ store, fields, setFields }: Props) {
  const { t } = useTranslation();
  const field = (key: string) => ({
    value: fields[key] ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setFields({ ...fields, [key]: e.currentTarget.value }),
    "data-testid": `object-store-${key}`,
  });
  if (store === "S3") {
    return (
      <>
        <FieldGroup>
          <FormField section="authentication" size="medium">
            <TextInput
              label={t("sourceFormFields.accessKeyId")}
              placeholder="${secret:aws_access_key_id}"
              {...field("access_key_id")}
            />
          </FormField>
          <FormField section="authentication" size="medium">
            <PasswordInput
              label={t("sourceFormFields.secretAccessKey")}
              placeholder="${secret:aws_secret_access_key}"
              {...field("secret_access_key")}
            />
          </FormField>
        </FieldGroup>
        <FormField size="medium">
          <TextInput
            label={t("sourceFormFields.region")}
            placeholder="us-east-1"
            {...field("region")}
          />
        </FormField>
        <FormField size="long">
          <TextInput
            label={t("sourceFormFields.s3EndpointMinio")}
            placeholder="optional — for S3-compatible"
            {...field("endpoint")}
          />
        </FormField>
      </>
    );
  }
  if (store === "GCS") {
    return (
      <>
        <FormField size="medium">
          <TextInput
            label={t("sourceFormFields.gcsHmacAccessId")}
            placeholder="${secret:gcs_hmac_access_id}"
            {...field("gcs_access_id")}
          />
        </FormField>
        <FormField section="authentication" size="medium">
          <PasswordInput
            label={t("sourceFormFields.gcsHmacSecret")}
            placeholder="${secret:gcs_hmac_secret}"
            {...field("gcs_secret_key")}
          />
        </FormField>
      </>
    );
  }
  return (
    <>
      <FormField size="medium">
        <TextInput label={t("sourceFormFields.storageAccount")} {...field("azure_account_name")} />
      </FormField>
      <FormField section="authentication" size="medium">
        <PasswordInput
          label={t("sourceFormFields.accessKey")}
          placeholder="${secret:azure_account_key}"
          {...field("azure_account_key")}
        />
      </FormField>
    </>
  );
}
