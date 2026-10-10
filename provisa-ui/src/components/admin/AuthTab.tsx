// Copyright (c) 2026 Kenneth Stott
// Canary: cdb0dd9f-7f52-440a-b1d7-c07ad4ab8132
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { missingRequired, secretPlaceholder } from "./secretFields";
import {
  Alert,
  Checkbox,
  PasswordInput,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { fetchAuthConfig, setAuthConfig, type AuthConfigState } from "../../api/admin";
import { PlatformRequired } from "./PlatformRequired";
import { isForbidden } from "./isForbidden";
import { FormChecks, FormField, FormFooter, FormLayout } from "../form/FormLayout";

// REQ-919: configure the authentication provider (firebase/keycloak/oauth/simple) + role settings.
// The provider binds at startup, so changes take effect on restart.
export function AuthTab() {
  const { t } = useTranslation();
  const [s, setS] = useState<AuthConfigState | null>(null);
  const [provider, setProvider] = useState("none");
  const [config, setConfig] = useState<Record<string, Record<string, string>>>({});
  const [common, setCommon] = useState<AuthConfigState["common"] | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    fetchAuthConfig()
      .then((a) => {
        setS(a);
        setProvider(a.provider);
        setCommon(a.common);
        const cfg: Record<string, Record<string, string>> = {};
        for (const [pk, vals] of Object.entries(a.config)) {
          cfg[pk] = {};
          for (const [k, v] of Object.entries(vals)) cfg[pk][k] = v == null ? "" : String(v);
        }
        setConfig(cfg);
      })
      .catch((e) => (isForbidden(e) ? setForbidden(true) : setError(String(e))));
  }, []);

  const current = useMemo(() => s?.providers.find((p) => p.key === provider), [s, provider]);

  // REQ-1575: a secret the server holds satisfies its required field without being retyped; the
  // server never sends it back, so the box is empty and that is not the same as unset.
  const incomplete = useMemo(
    () =>
      missingRequired(current?.config_fields ?? [], config[provider], s?.secret_set?.[provider]),
    [current, config, provider, s],
  );

  const save = async () => {
    if (!common) return;
    setSaving(true);
    setMsg("");
    setError("");
    try {
      const providerConfig: Record<string, unknown> = {};
      for (const f of current?.config_fields ?? []) {
        const v = (config[provider]?.[f.config_key] ?? "").trim();
        // REQ-1265: a true/false setting is always sent, as a boolean — unchecked is a value.
        if (f.type === "boolean") providerConfig[f.config_key] = v === "true";
        else if (v !== "") providerConfig[f.config_key] = v;
      }
      const res = await setAuthConfig({ provider, config: providerConfig, common });
      setMsg(res.restart_required ? t("authTab.savedRestartRequired") : t("authTab.saved"));
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (forbidden) return <PlatformRequired />;
  if (error && !s) return <Alert color="red">{error}</Alert>;
  if (!s || !common) return <Text>{t("authTab.loading")}</Text>;

  const setField = (key: string, value: string) =>
    setConfig((c) => ({ ...c, [provider]: { ...(c[provider] ?? {}), [key]: value } }));

  const providerOptions = s.providers.map((p) => ({
    value: p.key,
    label: p.key === s.provider ? `${p.label}${t("authTab.current")}` : p.label,
  }));

  const fields = current?.config_fields ?? [];
  return (
    <Stack gap="md">
      <Text c="dimmed" size="sm">
        {t("authTab.intro")}
      </Text>

      <FormLayout>
        <FormField size="medium">
          <Select
            label={t("authTab.providerLabel")}
            data={providerOptions}
            value={provider}
            onChange={(v) => v && setProvider(v)}
            allowDeselect={false}
            data-testid="auth-provider-select"
          />
        </FormField>
        {current && (
          <FormField size="full">
            <Text c="dimmed" size="xs">
              {current.description}
            </Text>
          </FormField>
        )}

        {fields
          .filter((f) => f.type !== "boolean")
          .map((f) =>
            f.secret ? (
              <FormField size="medium" key={f.config_key}>
                <PasswordInput
                  label={f.label}
                  required={f.required}
                  value={config[provider]?.[f.config_key] ?? ""}
                  placeholder={
                    secretPlaceholder(f, s.secret_set?.[provider], {
                      set: t("authTab.secretOnFile"),
                      unset: t("authTab.secretNotSet"),
                    }) ?? f.placeholder
                  }
                  autoComplete="new-password"
                  onChange={(e) => setField(f.config_key, e.currentTarget.value)}
                />
              </FormField>
            ) : (
              <FormField size="medium" key={f.config_key}>
                <TextInput
                  label={f.label}
                  required={f.required}
                  value={config[provider]?.[f.config_key] ?? ""}
                  placeholder={f.placeholder}
                  autoComplete="off"
                  onChange={(e) => setField(f.config_key, e.currentTarget.value)}
                />
              </FormField>
            ),
          )}

        <FormChecks>
          {fields
            .filter((f) => f.type === "boolean")
            .map((f) => (
              <FormField size="short" key={f.config_key}>
                <Checkbox
                  label={f.label}
                  checked={config[provider]?.[f.config_key] === "true"}
                  onChange={(e) => setField(f.config_key, String(e.currentTarget.checked))}
                />
              </FormField>
            ))}
          {provider === "basic" && (
            <FormField size="short">
              <Checkbox
                label={t("authTab.allowRegistration")}
                checked={common.allow_registration}
                onChange={(e) =>
                  setCommon({ ...common, allow_registration: e.currentTarget.checked })
                }
                data-testid="auth-allow-registration"
              />
            </FormField>
          )}
          {provider === "simple" && (
            <FormField size="short">
              <Checkbox
                label={t("authTab.allowSimpleAuth")}
                checked={common.allow_simple_auth}
                onChange={(e) =>
                  setCommon({ ...common, allow_simple_auth: e.currentTarget.checked })
                }
              />
            </FormField>
          )}
        </FormChecks>
      </FormLayout>

      <Title order={4}>{t("authTab.roles")}</Title>
      <FormLayout>
        <FormField size="medium">
          <TextInput
            label={t("authTab.defaultRole")}
            value={common.default_role}
            onChange={(e) => setCommon({ ...common, default_role: e.currentTarget.value })}
          />
        </FormField>
        <FormField size="medium">
          <Select
            label={t("authTab.assignmentsFrom")}
            data={[
              { value: "claims", label: t("authTab.assignmentsSourceClaims") },
              { value: "provisa", label: t("authTab.assignmentsSourceProvisa") },
            ]}
            value={common.assignments_source}
            onChange={(v) => v && setCommon({ ...common, assignments_source: v })}
            allowDeselect={false}
          />
        </FormField>
        <FormChecks>
          <FormField size="short">
            <Checkbox
              label={t("authTab.trustUpstream")}
              checked={common.trust_upstream}
              onChange={(e) => setCommon({ ...common, trust_upstream: e.currentTarget.checked })}
            />
          </FormField>
        </FormChecks>
      </FormLayout>

      <Alert color="yellow" variant="light">
        {s.restart_required_note}
      </Alert>

      <FormFooter
        onSave={save}
        saving={saving}
        saveProps={{ "data-testid": "auth-save-button", disabled: incomplete }}
      >
        {msg && (
          <Text c="green" size="sm">
            {msg}
          </Text>
        )}
        {error && (
          <Text c="red" size="sm">
            {error}
          </Text>
        )}
      </FormFooter>
    </Stack>
  );
}
