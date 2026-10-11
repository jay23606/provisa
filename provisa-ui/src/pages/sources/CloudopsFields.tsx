// Copyright (c) 2026 Kenneth Stott
// Canary: 7d4a2f95-6b18-4c03-9e7a-0f3d1b8c5e26
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1947: a cloud inventory source — the credentials and scope of one or more of Azure, AWS
// and GCP. Each secret may be a ${secret:…} reference.

import { Alert, Divider, PasswordInput, TextInput } from "@mantine/core";
import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import {
  CLOUDOPS_CLOUD_ORDER,
  CLOUDOPS_CLOUDS,
  cloudopsMissing,
  cloudopsNamedClouds,
  type CloudopsCloud,
} from "./cloudops";
import { FormField } from "../../components/form/FormLayout";

interface Props {
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

const CLOUD_LABEL: Record<CloudopsCloud, string> = {
  azure: "Azure",
  aws: "AWS",
  gcp: "GCP",
};

export function CloudopsFields({ fields, setFields }: Props) {
  const { t } = useTranslation();
  const named = cloudopsNamedClouds(fields);
  const missing = new Set(cloudopsMissing(fields));
  return (
    <>
      <FormField size="full">
        <Alert color={named.length ? "gray" : "yellow"} data-testid="cloudops-clouds-note">
          {named.length
            ? t("sourceFormFieldsExtended.coCloudsNamed", {
                clouds: named.map((c) => CLOUD_LABEL[c]).join(", "),
              })
            : t("sourceFormFieldsExtended.coNameACloud")}
        </Alert>
      </FormField>
      {CLOUDOPS_CLOUD_ORDER.map((cloud) => (
        <Fragment key={cloud}>
          <FormField size="full">
            <Divider label={CLOUD_LABEL[cloud]} labelPosition="left" />
          </FormField>
          {CLOUDOPS_CLOUDS[cloud].map((f) => {
            const props = {
              label: t(`sourceFormFieldsExtended.${f.label}`),
              required: f.required && named.includes(cloud),
              value: fields[f.key] ?? "",
              onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                setFields({ ...fields, [f.key]: e.currentTarget.value }),
              placeholder: f.placeholder,
              error: missing.has(f.key)
                ? t("sourceFormFieldsExtended.coRequiredWithCloud")
                : undefined,
              "data-testid": `cloudops-${f.key}`,
            };
            return f.secret ? (
              <FormField size="medium" key={f.key}>
                <PasswordInput {...props} />
              </FormField>
            ) : (
              <FormField size="medium" key={f.key}>
                <TextInput {...props} />
              </FormField>
            );
          })}
        </Fragment>
      ))}
      <FormField size="full">
        <Divider />
      </FormField>
      <FormField hint={t("sourceFormFieldsExtended.coCacheTtlMinutesHelp")} size="short">
        <TextInput
          label={t("sourceFormFieldsExtended.coCacheTtlMinutes")}
          value={fields.cache_ttl_minutes ?? ""}
          onChange={(e) => setFields({ ...fields, cache_ttl_minutes: e.currentTarget.value })}
          placeholder="5"
          data-testid="cloudops-cache_ttl_minutes"
        />
      </FormField>
    </>
  );
}
