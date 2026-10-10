// Copyright (c) 2026 Kenneth Stott
// Canary: 44d928ac-043b-4b7e-a911-7a3e5916acba
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Select, Stack, Text } from "@mantine/core";
import { fetchSecurity, setSecurity, type SecurityState } from "../../api/security";
import { FormField, FormFooter, FormLayout } from "../form/FormLayout";

// REQ-693: manage the platform security posture (security.mode). The posture binds at startup, so
// changes take effect on restart. mode=high is zero-trust: pgwire off, REST/GraphQL data 403.
export function SecurityTab() {
  const { t } = useTranslation();
  const [s, setS] = useState<SecurityState | null>(null);
  const [mode, setMode] = useState("standard");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    fetchSecurity()
      .then((e) => {
        setS(e);
        setMode(e.mode);
      })
      .catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  const current = useMemo(() => s?.modes.find((m) => m.key === mode), [s, mode]);

  const save = async () => {
    setSaving(true);
    setMsg("");
    setError("");
    try {
      const res = await setSecurity({ mode });
      setMsg(res.restart_required ? t("securityTab.savedRestartRequired") : t("securityTab.saved"));
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (error && !s) return <Alert color="red">{error}</Alert>;
  if (!s) return <Text>{t("securityTab.loading")}</Text>;

  const modeData = s.modes.map((m) => ({ value: m.key, label: m.label }));

  return (
    <Stack gap="md">
      <Text c="dimmed">{t("securityTab.intro")}</Text>

      <FormLayout>
        <FormField size="medium">
          <Select
            label={t("securityTab.modeLabel")}
            data={modeData}
            value={mode}
            onChange={(v) => v && setMode(v)}
            allowDeselect={false}
            data-testid="security-mode-select"
          />
        </FormField>
        {current && (
          <FormField size="full">
            <Text c="dimmed" fz="xs">
              {current.description}
            </Text>
          </FormField>
        )}
      </FormLayout>

      {mode === "high" && (
        <Alert
          color="red"
          variant="filled"
          title={t("securityTab.highWarningTitle")}
          data-testid="security-high-warning"
        >
          {t("securityTab.highWarning")}
        </Alert>
      )}

      <Alert color="yellow" variant="light">
        {s.restart_required_note}
      </Alert>

      <FormFooter onSave={save} saving={saving} saveProps={{ "data-testid": "security-save" }}>
        {msg && <Text c="green">{msg}</Text>}
        {error && <Text c="red">{error}</Text>}
      </FormFooter>
    </Stack>
  );
}
