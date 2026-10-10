// Copyright (c) 2026 Kenneth Stott
// Canary: 9338abaa-919a-4722-840e-a09ff09ef505
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1923: the mail platforms the organisation's sources connect to. For each platform an
// administrator enters the client the organisation registered with it, once; the address to
// register there is shown ready to copy. Nobody adding a source sees any of this.
//
// A credential field keeps what was typed -- the value, or a reference to a secret the
// administrator created -- and shows it again, behind the reveal control.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  Group,
  PasswordInput,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import {
  deleteMailPlatform,
  fetchMailPlatforms,
  putMailPlatform,
  type MailPlatforms,
} from "../../api/mailPlatforms";
import { useAuth } from "../../context/AuthContext";
import { draftOf, platformMissing, type Draft } from "./mailPlatformDraft";
import { FieldGroup, FormChecks, FormField, FormFooter, FormLayout } from "../form/FormLayout";

export function MailPlatformsSection() {
  const { t, i18n } = useTranslation();
  const { activeOrgId } = useAuth();
  const [state, setState] = useState<MailPlatforms | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState("");
  const [said, setSaid] = useState<{ platform: string; text: string; bad: boolean } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!activeOrgId) return;
    fetchMailPlatforms(activeOrgId)
      .then((answered) => {
        setState(answered);
        setDrafts(Object.fromEntries(answered.platforms.map((p) => [p.platform, draftOf(p)])));
      })
      .catch((e: unknown) => setError(String(e)));
  }, [activeOrgId]);
  useEffect(load, [load]);

  if (error) {
    return (
      <Alert color="red" variant="light" data-testid="mail-platforms-error">
        {error}
      </Alert>
    );
  }
  if (!state || !activeOrgId) return null;

  const change = (platform: string, patch: Partial<Draft>) =>
    setDrafts((d) => ({ ...d, [platform]: { ...d[platform], ...patch } }));

  const run = async (platform: string, act: () => Promise<unknown>, done: string) => {
    setBusy(platform);
    setSaid(null);
    try {
      await act();
      setSaid({ platform, text: done, bad: false });
      load();
    } catch (e) {
      setSaid({ platform, text: String(e), bad: true });
    } finally {
      setBusy("");
    }
  };

  return (
    <Stack gap="md">
      {state.platforms.map((p) => {
        const draft = drafts[p.platform] ?? draftOf(p);
        const id = `mail-platform-${p.platform}`;
        return (
          <Card key={p.platform} withBorder data-testid={id}>
            <Group justify="space-between" mb="sm">
              <Title order={4}>{t(`mailPlatforms.platform.${p.platform}`)}</Title>
              <Badge color={p.configured ? "green" : "gray"} data-testid={`${id}-state`}>
                {p.configured ? t("mailPlatforms.connected") : t("mailPlatforms.notConnected")}
              </Badge>
            </Group>
            <FormLayout>
              {state.redirect_address ? (
                <>
                  {/* The address to copy into the platform, with Copy at its end. */}
                  <FieldGroup row>
                    <FormField size="long" help={t(`mailPlatforms.redirectHelp.${p.platform}`)}>
                      <TextInput
                        label={t("mailPlatforms.redirectAddress")}
                        value={state.redirect_address}
                        readOnly
                        data-testid={`${id}-redirect`}
                      />
                    </FormField>
                    <CopyButton value={state.redirect_address}>
                      {({ copied, copy }) => (
                        <Button variant="default" onClick={copy} data-testid={`${id}-copy`}>
                          {copied ? t("mailPlatforms.copied") : t("mailPlatforms.copy")}
                        </Button>
                      )}
                    </CopyButton>
                  </FieldGroup>
                  <FormField size="full">
                    <Text size="xs" c="dimmed" data-testid={`${id}-same-address`}>
                      {t("mailPlatforms.sameAddressNote", {
                        origin: new URL(state.redirect_address).origin,
                      })}
                    </Text>
                  </FormField>
                </>
              ) : (
                <FormField size="full">
                  <Alert color="yellow" variant="light" data-testid={`${id}-no-redirect`}>
                    {t("mailPlatforms.redirectUnknown")}
                  </Alert>
                </FormField>
              )}
              {/* The client: its ID and its secret together. */}
              <FieldGroup>
                <FormField
                  size="medium"
                  help={p.organisation_key_field ? t("mailPlatforms.clientOptional") : undefined}
                >
                  <TextInput
                    label={t("mailPlatforms.clientId")}
                    required={!p.organisation_key_field}
                    value={draft.client_id}
                    onChange={(e) => change(p.platform, { client_id: e.currentTarget.value })}
                    data-testid={`${id}-client-id`}
                  />
                </FormField>
                <FormField size="medium">
                  <PasswordInput
                    label={t("mailPlatforms.clientSecret")}
                    required={!p.organisation_key_field}
                    value={draft.client_secret}
                    onChange={(e) => change(p.platform, { client_secret: e.currentTarget.value })}
                    data-testid={`${id}-client-secret`}
                  />
                </FormField>
              </FieldGroup>
              {p.settings_fields.map((field) => (
                <FormField size="medium" key={field} help={t(`mailPlatforms.settingHelp.${field}`)}>
                  <TextInput
                    label={t(`mailPlatforms.setting.${field}`)}
                    required
                    value={draft.settings[field] ?? ""}
                    onChange={(e) =>
                      change(p.platform, {
                        settings: { ...draft.settings, [field]: e.currentTarget.value },
                      })
                    }
                    data-testid={`${id}-setting-${field}`}
                  />
                </FormField>
              ))}
              {/* Whether sources may read the organization's mailboxes; what the administrator
                  grants at the platform for it is in the same help, where the platform has
                  wording. */}
              <FormChecks>
                <FormField
                  size="short"
                  help={
                    i18n.exists(`mailPlatforms.organisationGrant.${p.platform}`)
                      ? `${t("mailPlatforms.organisationMailboxesHelp")} ${t(`mailPlatforms.organisationGrant.${p.platform}`)}`
                      : t("mailPlatforms.organisationMailboxesHelp")
                  }
                >
                  <Switch
                    label={t("mailPlatforms.organisationMailboxes")}
                    checked={draft.organisation_mailboxes}
                    onChange={(e) =>
                      change(p.platform, { organisation_mailboxes: e.currentTarget.checked })
                    }
                    data-testid={`${id}-organisation-mailboxes`}
                  />
                </FormField>
              </FormChecks>
              {/* What the platform is entered with for those sources, where it has anything of
                  its own: the settings beside it, a credential, what to authorise. */}
              {p.organisation_settings_fields.map((field) => (
                <FormField size="medium" key={field} help={t(`mailPlatforms.settingHelp.${field}`)}>
                  <TextInput
                    label={t(`mailPlatforms.setting.${field}`)}
                    required={draft.organisation_mailboxes}
                    value={draft.settings[field] ?? ""}
                    onChange={(e) =>
                      change(p.platform, {
                        settings: { ...draft.settings, [field]: e.currentTarget.value },
                      })
                    }
                    data-testid={`${id}-setting-${field}`}
                  />
                </FormField>
              ))}
              {p.organisation_key_field && (
                <FormField size="long" help={t("mailPlatforms.organisationKeyHelp")}>
                  <PasswordInput
                    label={t("mailPlatforms.organisationKey")}
                    required={draft.organisation_mailboxes}
                    value={draft.organisation_key}
                    onChange={(e) =>
                      change(p.platform, { organisation_key: e.currentTarget.value })
                    }
                    data-testid={`${id}-organisation-key`}
                  />
                </FormField>
              )}
              {p.organisation_scopes.length > 0 && (
                <FieldGroup row>
                  <FormField size="long">
                    <TextInput
                      label={t("mailPlatforms.organisationScopes")}
                      value={p.organisation_scopes.join(",")}
                      readOnly
                      data-testid={`${id}-organisation-scopes`}
                    />
                  </FormField>
                  <CopyButton value={p.organisation_scopes.join(",")}>
                    {({ copied, copy }) => (
                      <Button
                        variant="default"
                        onClick={copy}
                        data-testid={`${id}-organisation-scopes-copy`}
                      >
                        {copied ? t("mailPlatforms.copied") : t("mailPlatforms.copy")}
                      </Button>
                    )}
                  </CopyButton>
                </FieldGroup>
              )}
              <FormFooter
                onSave={() =>
                  run(
                    p.platform,
                    () =>
                      putMailPlatform(activeOrgId, p.platform, {
                        client_id: draft.client_id.trim(),
                        ...(draft.client_secret ? { client_secret: draft.client_secret } : {}),
                        settings: draft.settings,
                        organisation_mailboxes: draft.organisation_mailboxes,
                        ...(draft.organisation_key
                          ? { organisation_key: draft.organisation_key }
                          : {}),
                      }),
                    t("mailPlatforms.saved"),
                  )
                }
                saving={busy === p.platform}
                saveProps={{
                  "data-testid": `${id}-save`,
                  disabled: platformMissing(p, draft).length > 0,
                }}
              >
                {p.configured && (
                  <Button
                    variant="default"
                    color="red"
                    onClick={() =>
                      run(
                        p.platform,
                        () => deleteMailPlatform(activeOrgId, p.platform),
                        t("mailPlatforms.removed"),
                      )
                    }
                    disabled={busy === p.platform}
                    data-testid={`${id}-remove`}
                  >
                    {t("mailPlatforms.remove")}
                  </Button>
                )}
                {said?.platform === p.platform && (
                  <Text size="sm" c={said.bad ? "red" : "green"} data-testid={`${id}-said`}>
                    {said.text}
                  </Text>
                )}
              </FormFooter>
            </FormLayout>
          </Card>
        );
      })}
    </Stack>
  );
}
