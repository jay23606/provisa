// Copyright (c) 2026 Kenneth Stott
// Canary: 359ca4ed-1eb0-49fb-a4f7-decbb82154e1
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.
// REQ-1923: a Google Workspace source -- whose mailbox, how much of it to read, which mail to
// hold, and one button to connect it; or the organisation's mailboxes (everyone, a group, a
// list), read with the organisation's own access once an administrator has allowed it. The
// person adding a source is asked nothing about how Provisa signs in to Google: the client and
// the service account are the organisation's, entered once by an administrator under
// Admin › Email. A source keeps only its owner's approval, or only which mailboxes.

import { useCallback, useEffect, useState } from "react";
import { Alert, Anchor, Button, Checkbox, Select, Text, TextInput, Textarea } from "@mantine/core";
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
  GOOGLE_WORKSPACE,
  GW_EVERYONE,
  GW_GROUP,
  GW_LIST,
  GW_MAIL_FULL,
  GW_MAIL_HEADERS,
  GW_ONE,
  GW_ORGANISATION,
  MAIL_PLATFORMS_ROUTE,
  gwCheckMailboxes,
  gwConnectMissing,
  gwHeadersOnly,
  gwMailboxes,
  gwMapping,
  gwOrganisation,
  gwResources,
  gwShapes,
} from "./googleWorkspace";
import { MailResourcesFields } from "./MailResourcesFields";
import { MAIL } from "./mailResources";
import { FieldGroup, FormChecks, FormField } from "../../components/form/FormLayout";
import { MailSinceField } from "./MailSinceField";

interface Props {
  sourceId: string;
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function GoogleWorkspaceFields({ sourceId, fields, setFields }: Props) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SignInStatus | null>(null);
  const [problem, setProblem] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [found, setFound] = useState<number | null>(null);
  const organisation = gwOrganisation(fields);
  const chosen = gwMailboxes(fields);
  const refused = useCallback(
    (err: unknown) =>
      serverMessage(
        err instanceof SignInRefused
          ? { code: err.code, params: err.params, detail: err.message }
          : null,
        t("googleWorkspaceFields.connectFailed"),
      ),
    [t],
  );

  // Whether the organisation has connected Google Workspace decides what the form offers.
  useEffect(() => {
    let live = true;
    signInStatus(GOOGLE_WORKSPACE)
      .then((answered) => live && setStatus(answered))
      .catch((err: unknown) => live && setProblem(refused(err)));
    return () => {
      live = false;
    };
  }, [refused]);

  // A new source opens on what the organisation's entry can do: an organisation that entered
  // no sign-in client reads its mailboxes, and is not told it has set nothing up. A stored
  // source states its shape and keeps it.
  useEffect(() => {
    if (status === null || fields.gw_whose) return;
    setFields({ ...fields, gw_whose: gwShapes(status, "").opensOn });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- decided once, when the entry is known
  }, [status]);

  // Whether this mailbox's owner has signed in is the server's to say: it keeps the approval.
  const account = (fields.gw_account ?? "").trim();
  useEffect(() => {
    if (!sourceId.trim() || !account) return;
    let live = true;
    signInStatus(GOOGLE_WORKSPACE, { source_id: sourceId, account })
      .then((answered) => {
        if (!live || !answered.connected) return;
        setFields({
          ...fields,
          gw_connected_as: account,
          gw_connected_at: answered.connected_at ?? "",
        });
      })
      .catch(() => undefined); // the organisation's status above already says what is wrong
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- asked when the mailbox named changes
  }, [sourceId, account]);

  const set = (key: string, value: string) => setFields({ ...fields, [key]: value });
  // A change to what Google was asked for is not what was approved: the approval is asked again.
  const setAsked = (key: string, value: string) => askAgain({ [key]: value });
  const askAgain = (changed: Record<string, string>) =>
    setFields({
      ...fields,
      ...changed,
      gw_connected_as: "",
      gw_connected_at: "",
      gw_earlier_approval: "",
    });
  const readsMail = gwResources(fields).includes(MAIL);
  const text = (key: string, change = set) => ({
    value: fields[key] ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      change(key, e.currentTarget.value),
    "data-testid": `google-workspace-${key}`,
  });
  // Another choice of mailboxes is not the one that was counted.
  const choose = (changed: Record<string, string>) => {
    setFound(null);
    setFields({ ...fields, ...changed });
  };

  const connect = async () => {
    setProblem("");
    setConnecting(true);
    try {
      const done = await signInSource({
        source_id: sourceId.trim(),
        kind: GOOGLE_WORKSPACE,
        account: fields.gw_account.trim(),
        // REQ-1994: the server asks Google for the scopes of what this mapping reads.
        mapping: gwMapping(fields),
      });
      setFields({
        ...fields,
        // The approval is kept by the server; the source holds none.
        gw_connected_as: done.account,
        gw_connected_at: new Date().toISOString(),
        gw_earlier_approval: "", // superseded by the approval just given
      });
    } catch (err) {
      setProblem(refused(err));
    } finally {
      setConnecting(false);
    }
  };

  const check = async () => {
    if (chosen === null) return;
    setProblem("");
    setFound(null);
    setChecking(true);
    try {
      setFound(await gwCheckMailboxes(chosen));
    } catch (err) {
      setProblem(refused(err));
    } finally {
      setChecking(false);
    }
  };

  // One mailbox is signed in to with the organisation's client; the organisation's mailboxes are
  // read with its service account, which an entry may hold with no client at all.
  // What the form offers follows what the organisation's entry can do.
  const shapes = gwShapes(status, fields.gw_whose ?? "");
  const notSetUp = !organisation && status !== null && !status.configured;
  const notAllowed = organisation && status !== null && !status.organisation_mailboxes;
  // Where an administrator sets it up, named as the menu names it in this language.
  const where = `${t("navBar.groupAdmin")} › ${t("navBar.itemEmail")}`;
  return (
    <>
      <FormField help={t("googleWorkspaceFields.whoseHelp")} size="medium">
        <Select
          label={t("googleWorkspaceFields.whose")}
          data={[
            { value: GW_ONE, label: t("googleWorkspaceFields.whoseOne") },
            { value: GW_ORGANISATION, label: t("googleWorkspaceFields.whoseOrganisation") },
          ].filter((choice) => shapes.offered.includes(choice.value))}
          value={organisation ? GW_ORGANISATION : GW_ONE}
          onChange={(value) => choose({ gw_whose: value ?? GW_ONE })}
          allowDeselect={false}
          data-testid="google-workspace-gw_whose"
        />
      </FormField>
      {!organisation && (
        <FieldGroup>
          {/* The button that connects the mailbox sits at the end of its address. */}
          <FormField
            section="authentication"
            hint={t("googleWorkspaceFields.accountHelp")}
            size="medium"
          >
            <TextInput
              label={t("googleWorkspaceFields.account")}
              placeholder="ada@example.com"
              required
              {...text("gw_account", setAsked)}
            />
          </FormField>
          {!notSetUp && (
            <Button
              type="button"
              onClick={connect}
              loading={connecting}
              disabled={status === null || gwConnectMissing(fields, sourceId).length > 0}
              data-testid="google-workspace-connect"
            >
              {t("googleWorkspaceFields.connect")}
            </Button>
          )}
        </FieldGroup>
      )}
      {organisation && (
        <>
          {/* The button that checks the choice sits at its end. */}
          <FieldGroup>
            <FormField size="medium">
              <Select
                label={t("googleWorkspaceFields.choice")}
                data={[
                  { value: GW_EVERYONE, label: t("googleWorkspaceFields.choiceEveryone") },
                  { value: GW_GROUP, label: t("googleWorkspaceFields.choiceGroup") },
                  { value: GW_LIST, label: t("googleWorkspaceFields.choiceList") },
                ]}
                value={fields.gw_choice ?? null}
                onChange={(value) => choose({ gw_choice: value ?? "" })}
                required
                allowDeselect={false}
                data-testid="google-workspace-gw_choice"
              />
            </FormField>
            {!notSetUp && !notAllowed && (
              <Button
                type="button"
                variant="default"
                onClick={check}
                loading={checking}
                disabled={status === null || chosen === null}
                data-testid="google-workspace-check"
              >
                {t("googleWorkspaceFields.check")}
              </Button>
            )}
          </FieldGroup>
          {fields.gw_choice === GW_GROUP && (
            <FormField hint={t("googleWorkspaceFields.groupHelp")} size="medium">
              <TextInput
                label={t("googleWorkspaceFields.group")}
                placeholder="sales@example.com"
                required
                value={fields.gw_group ?? ""}
                onChange={(e) => choose({ gw_group: e.currentTarget.value })}
                data-testid="google-workspace-gw_group"
              />
            </FormField>
          )}
          {fields.gw_choice === GW_LIST && (
            <FormField hint={t("googleWorkspaceFields.listHelp")} size="full">
              <Textarea
                label={t("googleWorkspaceFields.list")}
                placeholder={"ada@example.com\ngrace@example.com"}
                autosize
                minRows={3}
                required
                value={fields.gw_list ?? ""}
                onChange={(e) => choose({ gw_list: e.currentTarget.value })}
                data-testid="google-workspace-gw_list"
              />
            </FormField>
          )}
          <FormField size="full">
            <Text size="sm" c="dimmed" data-testid="google-workspace-every-mailbox">
              {t("googleWorkspaceFields.everyMailbox")}
            </Text>
          </FormField>
        </>
      )}
      <MailResourcesFields
        prefix="gw"
        testPrefix="google-workspace"
        fields={fields}
        setAsked={askAgain}
        set={(changed) => setFields({ ...fields, ...changed })}
        checkDays={false}
      />
      {readsMail && (
        <FormField hint={t("googleWorkspaceFields.mailContentHelp")} size="medium">
          <Select
            label={t("googleWorkspaceFields.mailContent")}
            data={[
              { value: GW_MAIL_FULL, label: t("googleWorkspaceFields.mailContentFull") },
              { value: GW_MAIL_HEADERS, label: t("googleWorkspaceFields.mailContentHeaders") },
            ]}
            value={fields.gw_mail_content ?? null}
            onChange={(value) => setAsked("gw_mail_content", value ?? "")}
            required
            allowDeselect={false}
            data-testid="google-workspace-gw_mail_content"
          />
        </FormField>
      )}
      {notSetUp && (
        <FormField size="full">
          <Alert color="yellow" variant="light" data-testid="google-workspace-not-set-up">
            {status.may_configure ? (
              <>
                {t("googleWorkspaceFields.notSetUp")}{" "}
                <Anchor
                  component={Link}
                  to={MAIL_PLATFORMS_ROUTE}
                  data-testid="google-workspace-set-up"
                >
                  {t("googleWorkspaceFields.setUpLink", { where })}
                </Anchor>
              </>
            ) : (
              t("googleWorkspaceFields.notSetUpAsk", { where })
            )}
          </Alert>
        </FormField>
      )}
      {notAllowed && (
        <FormField size="full">
          <Alert color="yellow" variant="light" data-testid="google-workspace-not-allowed">
            {status.may_configure ? (
              <>
                {t("googleWorkspaceFields.notAllowed")}{" "}
                <Anchor
                  component={Link}
                  to={MAIL_PLATFORMS_ROUTE}
                  data-testid="google-workspace-allow"
                >
                  {t("googleWorkspaceFields.allowLink", { where })}
                </Anchor>
              </>
            ) : (
              t("googleWorkspaceFields.notAllowedAsk", { where })
            )}
          </Alert>
        </FormField>
      )}
      {organisation && !notSetUp && !notAllowed && found !== null && (
        <FormField size="full">
          <Alert color="green" variant="light" py={4} px="sm" data-testid="google-workspace-found">
            {t("googleWorkspaceFields.found", { count: found })}
          </Alert>
        </FormField>
      )}
      {!organisation && !notSetUp && fields.gw_connected_as && (
        <FormField size="full">
          <Alert
            color="green"
            variant="light"
            py={4}
            px="sm"
            data-testid="google-workspace-connected"
          >
            {fields.gw_connected_at
              ? t("googleWorkspaceFields.connectedOn", {
                  account: fields.gw_connected_as,
                  date: new Date(fields.gw_connected_at).toLocaleDateString(),
                })
              : t("googleWorkspaceFields.connected", { account: fields.gw_connected_as })}
          </Alert>
        </FormField>
      )}
      {problem && (
        <FormField size="full">
          <Alert color="red" variant="light" data-testid="google-workspace-problem">
            {problem}
          </Alert>
        </FormField>
      )}
      {/* Google does not search mail it serves as headers and labels only. */}
      {readsMail && !gwHeadersOnly(fields) && (
        <>
          <FormField
            // What a search costs is said once one is typed: only Google can say what a search
            // matches, so such a source cannot be asked what changed and is read again whole.
            hint={t(
              (fields.gw_mail_search ?? "").trim()
                ? "googleWorkspaceFields.mailSearchCost"
                : "googleWorkspaceFields.mailSearchHelp",
            )}
            size="long"
          >
            <TextInput
              label={t("googleWorkspaceFields.mailSearch")}
              placeholder="from:orders@example.com"
              {...text("gw_mail_search")}
            />
          </FormField>
          <MailSinceField
            value={fields.gw_mail_since ?? ""}
            onChange={(value) => set("gw_mail_since", value)}
            testId="google-workspace-gw_mail_since"
          />
        </>
      )}
      {readsMail && (
        <>
          <FormField hint={t("googleWorkspaceFields.mailLabelsHelp")} size="full">
            <Textarea
              label={t("googleWorkspaceFields.mailLabels")}
              placeholder={"Clients\nInvoices"}
              autosize
              minRows={2}
              {...text("gw_mail_labels")}
            />
          </FormField>
          <FormChecks>
            <FormField size="long">
              <Checkbox
                label={t("googleWorkspaceFields.mailSpamTrash")}
                checked={fields.gw_mail_include_spam_trash === "true"}
                onChange={(e) =>
                  set("gw_mail_include_spam_trash", e.currentTarget.checked ? "true" : "")
                }
                data-testid="google-workspace-gw_mail_include_spam_trash"
              />
            </FormField>
          </FormChecks>
        </>
      )}
    </>
  );
}
