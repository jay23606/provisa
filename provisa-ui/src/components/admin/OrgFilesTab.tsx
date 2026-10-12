// Copyright (c) 2026 Kenneth Stott
// Canary: 5a8d1e36-9c2b-4f07-b4e1-3d6f8a2c0e95
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Checkbox, Code, List, Stack, Text, TextInput } from "@mantine/core";
import {
  fetchOrgFiles,
  generateOrgFilesKey,
  setOrgFiles,
  type OrgFilesState,
} from "../../api/admin";
import { FormChecks, FormField, FormFooter, FormLayout } from "../form/FormLayout";

/** A key is named by a reference into the organization's vault, never entered itself. */
const REFERENCE = /^\$\{secret:[^}]+\}$/;
const WARNINGS = ["warn1", "warn2", "warn3", "warn4", "warn5", "warn6"] as const;

/**
 * REQ-1992: whether the org's file folder is encrypted, under a key the org holds in its own
 * vault. The page names the key by reference; a generated key is shown once and kept by nobody.
 */
export function OrgFilesTab() {
  const { t } = useTranslation();
  const [s, setS] = useState<OrgFilesState | null>(null);
  const [encrypted, setEncrypted] = useState(false);
  const [reference, setReference] = useState("");
  const [generated, setGenerated] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchOrgFiles()
      .then((state) => {
        setS(state);
        setEncrypted(state.encrypted);
        setReference(state.key_reference ?? "");
      })
      .catch((e) => setError(String(e)));
  }, []);

  const trimmed = reference.trim();
  const referenceWrong = trimmed !== "" && !REFERENCE.test(trimmed);
  const missing = encrypted && trimmed === "";

  const generate = async () => {
    setError("");
    try {
      setGenerated(await generateOrgFilesKey());
    } catch (e) {
      setError(String(e));
    }
  };

  const save = async () => {
    setSaving(true);
    setMsg("");
    setError("");
    try {
      setS(await setOrgFiles({ encrypted, key_reference: trimmed || null }));
      setMsg(t("orgFilesTab.saved"));
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (error && !s) return <Alert color="red">{error}</Alert>;
  if (!s) return <Text>{t("orgFilesTab.loading")}</Text>;

  return (
    <Stack gap="md" data-testid="org-files">
      <Text c="dimmed" size="sm">
        {t("orgFilesTab.intro")}
      </Text>
      <FormLayout>
        <FormChecks>
          <FormField size="long">
            <Checkbox
              label={t("orgFilesTab.encrypt")}
              checked={encrypted}
              onChange={(e) => setEncrypted(e.currentTarget.checked)}
              data-testid="org-files-encrypt"
            />
          </FormField>
        </FormChecks>
        <FormField help={t("orgFilesTab.referenceHelp")} size="long">
          <TextInput
            label={t("orgFilesTab.referenceLabel")}
            placeholder="${secret:provisa_files_key}"
            value={reference}
            required={encrypted}
            error={referenceWrong ? t("orgFilesTab.referenceWrong") : undefined}
            onChange={(e) => setReference(e.currentTarget.value)}
            data-testid="org-files-reference"
          />
        </FormField>
      </FormLayout>
      <Button variant="default" onClick={generate} w="fit-content" data-testid="org-files-generate">
        {t("orgFilesTab.generate")}
      </Button>
      {generated && (
        <Stack gap={4} data-testid="org-files-generated">
          <Text fw={600}>{t("orgFilesTab.generatedLabel")}</Text>
          <Code block data-testid="org-files-generated-key">
            {generated}
          </Code>
          <Text size="xs" c="dimmed">
            {t("orgFilesTab.generatedHelp")}
          </Text>
        </Stack>
      )}
      {(generated || trimmed) && (
        <Alert
          color="yellow"
          variant="light"
          title={t("orgFilesTab.warnTitle")}
          data-testid="org-files-warning"
        >
          <List size="sm">
            {WARNINGS.map((key) => (
              <List.Item key={key}>{t(`orgFilesTab.${key}`)}</List.Item>
            ))}
          </List>
        </Alert>
      )}
      <FormFooter
        onSave={save}
        saving={saving}
        saveProps={{ "data-testid": "org-files-save", disabled: referenceWrong || missing }}
      >
        {msg && <Text c="green">{msg}</Text>}
        {error && <Text c="red">{error}</Text>}
      </FormFooter>
    </Stack>
  );
}
