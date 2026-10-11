// Copyright (c) 2026 Kenneth Stott
// Canary: 155ecdd1-050c-4863-8952-862519d02f04
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-788: a files source may be registered as ONE logical table over a glob of files, with an
// optional column carrying each row's file path. Extracted from RegisterTableForm so that form
// stays within its line budget.

import { Fragment } from "react";
import { TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormField } from "../../components/form/FormLayout";

export function FilesGlobFieldset({
  fileGlob,
  setFileGlob,
  sourceFileColumn,
  setSourceFileColumn,
}: {
  fileGlob: string;
  setFileGlob: (v: string) => void;
  sourceFileColumn: string;
  setSourceFileColumn: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Fragment>
      <FormField size="long" hint={t("registerTableForm.fileGlobHint")}>
        <TextInput
          label={t("registerTableForm.fileGlobLabel")}
          placeholder={t("registerTableForm.fileGlobPlaceholder")}
          value={fileGlob}
          onChange={(e) => setFileGlob(e.currentTarget.value)}
          data-testid="register-table-file-glob"
        />
      </FormField>
      <FormField size="medium" hint={t("registerTableForm.sourceFileColumnHint")}>
        <TextInput
          label={t("registerTableForm.sourceFileColumnLabel")}
          placeholder={t("registerTableForm.sourceFileColumnPlaceholder")}
          value={sourceFileColumn}
          onChange={(e) => setSourceFileColumn(e.currentTarget.value)}
          disabled={!fileGlob.trim()}
          data-testid="register-table-source-file-column"
        />
      </FormField>
    </Fragment>
  );
}
