// Copyright (c) 2026 Kenneth Stott
// Canary: 2c8f1b8c-cf98-4cd1-b373-375394da05b5
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.
// REQ-1923: a Microsoft 365 source -- whose mail, what is read, and one button. It has two
// shapes: one mailbox, which its owner connects, and the organisation's mailboxes (everyone, a
// group, or a list), read with the organisation's own credential once an administrator has
// allowed it. The person adding a source is asked nothing about how Provisa signs in to
// Microsoft: the client is the organisation's, entered once under Admin › Email.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Anchor,
  Button,
  Checkbox,
  Group,
  Select,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { serverMessage } from "../../i18n/serverMessage";
import {
  SignInRefused,
  signInSource,
  signInStatus,
  type SignInStatus,
} from "../../lib/sourceSignIn";
import {
  MAIL_PLATFORMS_ROUTE,
  MICROSOFT_365,
  M365_EVERYONE,
  M365_GROUP,
  M365_LIST,
  M365_ONE,
  M365_ORGANISATION,
  M365_SCOPES,
  m365CheckMailboxes,
  m365ConnectMissing,
  m365Mailboxes,
  m365Organisation,
} from "./microsoft365";
import { FieldGroup, FormChecks, FormField } from "../../components/form/FormLayout";

interface Props {
  sourceId: string;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function Microsoft365Fields({ sourceId, fields, setFields }: Props) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SignInStatus | null>(null);
  const [problem, setProblem] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [found, setFound] = useState<number | null>(null);
  const organisation = m365Organisation(fields);
  const chosen = m365Mailboxes(fields);
  const refused = useCallback(
    (err: unknown) =>
      serverMessage(
        err instanceof SignInRefused
          ? { code: err.code, params: err.params, detail: err.message }
          : null,
        t("microsoft365Fields.connectFailed"),
      ),
    [t],
  );

  // Whether the organisation has connected Microsoft 365 decides what the form offers.
  useEffect(() => {
    let live = true;
    signInStatus(MICROSOFT_365)
      .then((answered) => live && setStatus(answered))
      .catch((err: unknown) => live && setProblem(refused(err)));
    return () => {
      live = false;
    };
  }, [refused]);

  // Whether this mailbox's owner has signed in is the server's to say: it keeps the approval.
  const account = (fields.m365_account ?? "").trim();
  useEffect(() => {
    if (!sourceId.trim() || !account) return;
    let live = true;
    signInStatus(MICROSOFT_365, { source_id: sourceId, account })
      .then((answered) => {
        if (!live || !answered.connected) return;
        setFields({
          ...fields,
          m365_connected_as: account,
          m365_connected_at: answered.connected_at ?? "",
        });
      })
      .catch(() => undefined); // the organisation's status above already says what is wrong
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- asked when the mailbox named changes
  }, [sourceId, account]);

  const connect = async () => {
    setProblem("");
    setConnecting(true);
    try {
      const done = await signInSource({
        source_id: sourceId.trim(),
        kind: MICROSOFT_365,
        account: fields.m365_account.trim(),
        scopes: M365_SCOPES,
      });
      setFields({
        ...fields,
        m365_connected_as: done.account,
        m365_connected_at: new Date().toISOString(),
        m365_earlier_approval: "", // superseded by the approval just given
      });
    } catch (err) {
      setProblem(refused(err));
    } finally {
      setConnecting(false);
    }
  };

  // Another choice of mailboxes is not the one that was counted.
  const choose = (changed: Record<string, string>) => {
    setFound(null);
    setFields({ ...fields, ...changed });
  };

  const check = async () => {
    if (chosen === null) return;
    setProblem("");
    setFound(null);
    setChecking(true);
    try {
      setFound(await m365CheckMailboxes(chosen));
    } catch (err) {
      setProblem(refused(err));
    } finally {
      setChecking(false);
    }
  };

  const notSetUp = status !== null && !status.configured;
  const notAllowed =
    organisation && status !== null && status.configured && !status.organisation_mailboxes;
  // Where an administrator sets it up, named as the menu names it in this language.
  const where = `${t("navBar.groupAdmin")} › ${t("navBar.itemEmail")}`;
  return (
    <>
      <FormField help={t("microsoft365Fields.whoseHelp")} size="medium">
        <Select
          label={t("microsoft365Fields.whose")}
          data={[
            { value: M365_ONE, label: t("microsoft365Fields.whoseOne") },
            { value: M365_ORGANISATION, label: t("microsoft365Fields.whoseOrganisation") },
          ]}
          value={organisation ? M365_ORGANISATION : M365_ONE}
          onChange={(value) => choose({ m365_whose: value ?? M365_ONE })}
          allowDeselect={false}
          data-testid="microsoft-365-m365_whose"
        />
      </FormField>
      {!organisation && (
        <>
          {/* The button that connects the mailbox sits at the end of its address. */}
          <FieldGroup>
            <FormField hint={t("microsoft365Fields.accountHelp")} size="medium">
              <TextInput
                label={t("microsoft365Fields.account")}
                placeholder="ada@example.com"
                required
                value={fields.m365_account ?? ""}
                // Another mailbox is not the one that was approved: the approval is asked again.
                onChange={(e) =>
                  setFields({
                    ...fields,
                    m365_account: e.currentTarget.value,
                    m365_earlier_approval: "",
                    m365_connected_as: "",
                    m365_connected_at: "",
                  })
                }
                data-testid="microsoft-365-m365_account"
              />
            </FormField>
            {!notSetUp && (
              <Button
                type="button"
                onClick={connect}
                loading={connecting}
                disabled={status === null || m365ConnectMissing(fields, sourceId).length > 0}
                data-testid="microsoft-365-connect"
              >
                {t("microsoft365Fields.connect")}
              </Button>
            )}
          </FieldGroup>
          <FormChecks>
            <FormField help={t("microsoft365Fields.readsMailHelp")} size="short">
              <Checkbox
                label={t("microsoft365Fields.readsMail")}
                checked
                readOnly
                data-testid="microsoft-365-reads-mail"
              />
            </FormField>
          </FormChecks>
        </>
      )}
      {organisation && (
        <>
          <FormField size="medium">
            <Select
              label={t("microsoft365Fields.choice")}
              data={[
                { value: M365_EVERYONE, label: t("microsoft365Fields.choiceEveryone") },
                { value: M365_GROUP, label: t("microsoft365Fields.choiceGroup") },
                { value: M365_LIST, label: t("microsoft365Fields.choiceList") },
              ]}
              value={fields.m365_choice ?? null}
              onChange={(value) => choose({ m365_choice: value ?? "" })}
              required
              allowDeselect={false}
              data-testid="microsoft-365-m365_choice"
            />
          </FormField>
          {fields.m365_choice === M365_GROUP && (
            <FormField help={t("microsoft365Fields.groupHelp")} size="medium">
              <TextInput
                label={t("microsoft365Fields.group")}
                placeholder="sales@example.com"
                required
                value={fields.m365_group ?? ""}
                onChange={(e) => choose({ m365_group: e.currentTarget.value })}
                data-testid="microsoft-365-m365_group"
              />
            </FormField>
          )}
          {fields.m365_choice === M365_LIST && (
            <FormField hint={t("microsoft365Fields.listHelp")} size="full">
              <Textarea
                label={t("microsoft365Fields.list")}
                placeholder={"ada@example.com\ngrace@example.com"}
                autosize
                minRows={3}
                required
                value={fields.m365_list ?? ""}
                onChange={(e) => choose({ m365_list: e.currentTarget.value })}
                data-testid="microsoft-365-m365_list"
              />
            </FormField>
          )}
          <FormChecks>
            <FormField help={t("microsoft365Fields.readsMailHelp")} size="short">
              <Checkbox
                label={t("microsoft365Fields.readsMail")}
                checked
                readOnly
                data-testid="microsoft-365-reads-mail"
              />
            </FormField>
          </FormChecks>
          <FormField size="full">
            <Text size="sm" c="dimmed" data-testid="microsoft-365-every-mailbox">
              {t("microsoft365Fields.everyMailbox")}
            </Text>
          </FormField>
        </>
      )}
      {notSetUp && (
        <FormField size="full">
          <Alert color="yellow" variant="light" data-testid="microsoft-365-not-set-up">
            {status.may_configure ? (
              <>
                {t("microsoft365Fields.notSetUp")}{" "}
                <Anchor
                  component={Link}
                  to={MAIL_PLATFORMS_ROUTE}
                  data-testid="microsoft-365-set-up"
                >
                  {t("microsoft365Fields.setUpLink", { where })}
                </Anchor>
              </>
            ) : (
              t("microsoft365Fields.notSetUpAsk", { where })
            )}
          </Alert>
        </FormField>
      )}
      {notAllowed && (
        <FormField size="full">
          <Alert color="yellow" variant="light" data-testid="microsoft-365-not-allowed">
            {status.may_configure ? (
              <>
                {t("microsoft365Fields.notAllowed")}{" "}
                <Anchor
                  component={Link}
                  to={MAIL_PLATFORMS_ROUTE}
                  data-testid="microsoft-365-allow"
                >
                  {t("microsoft365Fields.allowLink", { where })}
                </Anchor>
              </>
            ) : (
              t("microsoft365Fields.notAllowedAsk", { where })
            )}
          </Alert>
        </FormField>
      )}
      {organisation && !notSetUp && !notAllowed && (
        <FormField size="full">
          <Group gap="sm" align="center">
            <Button
              type="button"
              variant="default"
              onClick={check}
              loading={checking}
              disabled={status === null || chosen === null}
              data-testid="microsoft-365-check"
            >
              {t("microsoft365Fields.check")}
            </Button>
            {found !== null && (
              <Alert color="green" variant="light" py={4} px="sm" data-testid="microsoft-365-found">
                {t("microsoft365Fields.found", { count: found })}
              </Alert>
            )}
          </Group>
        </FormField>
      )}
      {!organisation && !notSetUp && fields.m365_connected_as && (
        <FormField size="full">
          <Alert color="green" variant="light" py={4} px="sm" data-testid="microsoft-365-connected">
            {fields.m365_connected_at
              ? t("microsoft365Fields.connectedOn", {
                  account: fields.m365_connected_as,
                  date: new Date(fields.m365_connected_at).toLocaleDateString(),
                })
              : t("microsoft365Fields.connected", { account: fields.m365_connected_as })}
          </Alert>
        </FormField>
      )}
      {problem && (
        <FormField size="full">
          <Alert color="red" variant="light" data-testid="microsoft-365-problem">
            {problem}
          </Alert>
        </FormField>
      )}
    </>
  );
}
