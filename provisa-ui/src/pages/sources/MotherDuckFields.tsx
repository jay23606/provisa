// Copyright (c) 2026 Kenneth Stott
// Canary: 6feffd5b-f26d-4163-bbd6-45bda2d29650
//
// This source code is licensed under the Business Source License 1.1

// REQ-1998: a MotherDuck database -- the database (or a share, by its address) and the token it
// signs in with. A statement joining a local DuckDB file with it may send the file's rows to the
// MotherDuck account (dual execution), so the form says so.

import { Alert, PasswordInput, TextInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FieldGroup, FormField } from "../../components/form/FormLayout";
import type { SourceFormState } from "./SourceFormFields";

export const MOTHERDUCK = "motherduck";

interface Props {
  form: SourceFormState;
  setForm: (form: SourceFormState) => void;
}

export function MotherDuckFields({ form, setForm }: Props) {
  const { t } = useTranslation();
  return (
    <>
      <FieldGroup>
        <FormField size="long" hint={t("motherDuckFields.databaseHint")}>
          <TextInput
            required
            label={t("motherDuckFields.database")}
            placeholder="my_db"
            value={form.database}
            onChange={(e) => setForm({ ...form, database: e.currentTarget.value })}
            data-testid="motherduck-database"
          />
        </FormField>
        <FormField size="medium" hint={t("motherDuckFields.tokenHint")}>
          <PasswordInput
            required
            label={t("motherDuckFields.token")}
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.currentTarget.value })}
            data-testid="motherduck-token"
          />
        </FormField>
      </FieldGroup>
      <Alert color="yellow" data-testid="motherduck-data-movement">
        {t("motherDuckFields.dataMovement")}
      </Alert>
    </>
  );
}
