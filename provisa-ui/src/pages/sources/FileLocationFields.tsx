// Copyright (c) 2026 Kenneth Stott
// Canary: 935594e3-4a77-4341-88b1-ef64961d6847
//
// This source code is licensed under the Business Source License 1.1

// REQ-1997: a file-based source's file -- its location, or the file itself by upload. A DuckDB
// file's location is kept in `database` (SourcesPage sends it as the path); while the location
// is the source's uploaded file it is not edited as text.

import { TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import { SourceFileUpload } from "./SourceFileUpload";
import type { SourceFormState } from "./SourceFormFields";
import { FILE_DATABASES, fileLocationOf, isUploadPath } from "./sourceUpload";

interface Props {
  form: SourceFormState;
  setForm: (form: SourceFormState) => void;
}

export function FileLocationFields({ form, setForm }: Props) {
  const { t } = useTranslation();
  const location = fileLocationOf(form);
  const setLocation = (value: string) =>
    setForm(form.type === "duckdb" ? { ...form, database: value } : { ...form, path: value });
  const uploaded = isUploadPath(location, form.id);
  return (
    <FieldGroup>
      <FormField
        size="long"
        hint={t(
          uploaded
            ? "sourceFormFields.uploadedFileHint"
            : FILE_DATABASES.has(form.type)
              ? "sourceFormFields.fileDatabaseLocationsHint"
              : "sourceFormFields.fileLocationsHint",
        )}
      >
        <TextInput
          label={
            form.type === "duckdb"
              ? t("sourceFormFields.filePath")
              : form.type === "sqlite"
                ? t("sourceFormFields.sqliteFilePath")
                : form.type === "csv"
                  ? t("sourceFormFields.csvFilePath")
                  : t("sourceFormFields.parquetFilePath")
          }
          required
          readOnly={uploaded}
          value={location}
          onChange={(e) => setLocation(e.currentTarget.value)}
          placeholder={
            form.type === "duckdb"
              ? t("sourceFormFields.filePathPlaceholder")
              : form.type === "sqlite"
                ? "./demo/files/orders.sqlite"
                : form.type === "csv"
                  ? "./demo/files/customers.csv"
                  : "./demo/files/products.parquet"
          }
          data-testid="source-file-location"
        />
      </FormField>
      <SourceFileUpload
        sourceId={form.id}
        type={form.type}
        uploaded={uploaded}
        onUploaded={setLocation}
      />
    </FieldGroup>
  );
}
