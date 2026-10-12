// Copyright (c) 2026 Kenneth Stott
// Canary: f5b0ab20-6bc3-4d64-a2ab-416967afdcdd
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A command's read view: every value of the function or webhook, under the labels the form gives
// them, an empty one as the shared empty mark. The form's fields that depend on how a function is
// implemented are shown for that implementation only, as the form shows them.

import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Text } from "@mantine/core";
import type {
  ActionArg,
  DatasetColumn,
  InlineField,
  TrackedFunction,
  TrackedWebhook,
} from "../../api/actions";
import { DetailFields, type DetailField } from "../../components/detail/DetailFields";
import { IMPL_KINDS } from "./types";

function ReadHeading({ children }: { children: string }) {
  return (
    <Text fw={700} c="dimmed" fz="0.75rem" tt="uppercase" mb="xs">
      {children}
    </Text>
  );
}

const roles = (list: readonly string[] | null | undefined) =>
  list && list.length > 0 ? list.join(", ") : null;

const args = (list: readonly ActionArg[]) =>
  list.length > 0 ? list.map((a) => `${a.name}: ${a.type}`).join(", ") : null;

/** Who sees each column of the response and how it is masked, one group per column. */
function ResponseColumns({
  title,
  columns,
  testId,
}: {
  title: string;
  columns: readonly (DatasetColumn | InlineField)[];
  testId: string;
}) {
  const { t } = useTranslation();
  const maskLabel: Record<string, string> = {
    regex: t("commandFormFields.maskRegex"),
    constant: t("commandFormFields.maskConstant"),
    truncate: t("commandFormFields.maskTruncate"),
  };
  return (
    <>
      <ReadHeading>{title}</ReadHeading>
      {columns.length === 0 ? (
        <DetailFields testId={testId} fields={[{ label: title, value: null }]} />
      ) : (
        columns.map((c) => {
          const mask: DetailField[] =
            c.mask_type === "regex"
              ? [
                  { label: t("commandFormFields.maskPattern"), value: c.mask_pattern },
                  { label: t("commandFormFields.maskReplace"), value: c.mask_replace },
                ]
              : c.mask_type === "constant"
                ? [{ label: t("commandFormFields.maskValue"), value: c.mask_value }]
                : c.mask_type === "truncate"
                  ? [{ label: t("commandFormFields.maskPrecision"), value: c.mask_precision }]
                  : [];
          return (
            <Fragment key={c.name}>
              <Text size="sm" fw={600} ff="monospace" mb={4}>
                {`${c.name}: ${c.type}`}
              </Text>
              <DetailFields
                testId={`${testId}-${c.name}`}
                fields={[
                  {
                    // Blank is everyone, as the form's label says.
                    label: t("commandFormFields.colVisibleTo"),
                    value: roles(c.visible_to) ?? t("commandsPage.all"),
                  },
                  {
                    label: t("commandFormFields.colMask"),
                    value: c.mask_type ? maskLabel[c.mask_type] : t("commandFormFields.maskNone"),
                  },
                  ...mask,
                  { label: t("commandFormFields.colUnmaskedTo"), value: roles(c.unmasked_to) },
                ]}
              />
            </Fragment>
          );
        })
      )}
    </>
  );
}

/** What every command has, function or webhook: its name, type, kind, domain and description. */
function useCommonFields(c: TrackedFunction | TrackedWebhook, type: "function" | "webhook") {
  const { t } = useTranslation();
  return {
    head: [
      { label: t("commandsPage.nameLabel"), value: c.name },
      {
        label: t("commandsPage.typeLabel"),
        value: type === "function" ? t("commandsPage.typeFunction") : t("commandsPage.typeWebhook"),
      },
      {
        label: t("commandFormFields.kind"),
        value: c.kind === "query" ? t("commandFormFields.query") : t("commandFormFields.mutation"),
      },
      { label: t("commandFormFields.domain"), value: c.domainId },
    ],
    tail: [
      { label: t("commandFormFields.description"), value: c.description },
      { label: t("commandFormFields.arguments"), value: args(c.arguments) },
    ],
  };
}

export function FunctionRead({
  fn,
  productName,
}: {
  fn: TrackedFunction;
  /** The data product it belongs to, by name; null when it belongs to none. */
  productName: string | null;
}) {
  const { t } = useTranslation();
  const common = useCommonFields(fn, "function");
  const impl = fn.implKind ?? "source_procedure";
  const binding = fn.binding ?? {};
  const bound = (key: string) => {
    const v = binding[key];
    if (v === null || v === undefined) return null;
    return Array.isArray(v) ? v.join(" ") : String(v);
  };
  const yesNo = (v: boolean) => (v ? t("commandsPage.yes") : t("commandsPage.no"));
  const bySource = impl === "source_procedure" || impl === "source_operation";
  const implementation: DetailField[] = bySource
    ? [
        { label: t("commandFormFields.source"), value: fn.sourceId },
        { label: t("commandFormFields.schema"), value: fn.schemaName },
        { label: t("commandFormFields.functionName"), value: fn.functionName },
      ]
    : impl === "script"
      ? [{ label: t("commandFormFields.bindingArgv"), value: bound("argv") }]
      : impl === "http"
        ? [
            { label: t("commandFormFields.bindingUrl"), value: bound("url") },
            { label: t("commandFormFields.method"), value: bound("method") },
          ]
        : impl === "grpc"
          ? [
              { label: t("commandFormFields.bindingTarget"), value: bound("target") },
              { label: t("commandFormFields.bindingGrpcMethod"), value: bound("method") },
              { label: t("commandFormFields.bindingTls"), value: yesNo(Boolean(binding.tls)) },
            ]
          : [{ label: t("commandFormFields.bindingCallable"), value: bound("callable") }];
  const toTable = Boolean(fn.returns);
  return (
    <div className="detail-groups" data-testid={`function-read-${fn.name}`}>
      <DetailFields
        testId="function-read-fields"
        fields={[
          ...common.head,
          { label: t("commandFormFields.dataProduct"), value: productName },
          {
            label: t("commandFormFields.implementation"),
            value: IMPL_KINDS.find((k) => k.value === impl)?.label ?? impl,
          },
          ...implementation,
          ...(bySource
            ? []
            : [
                {
                  label: t("commandFormFields.materialize"),
                  value: yesNo(Boolean(fn.materialize)),
                },
              ]),
          {
            label: t("commandFormFields.returnType"),
            value: toTable
              ? t("commandFormFields.registeredTable")
              : t("commandFormFields.datasetColumns"),
          },
          ...(toTable ? [{ label: t("commandFormFields.returnsTable"), value: fn.returns }] : []),
          {
            label: t("commandFormFields.visibleTo"),
            value: roles(fn.visibleTo) ?? t("commandsPage.all"),
          },
          { label: t("commandFormFields.writesTable"), value: fn.writesTable },
          {
            label: t("commandFormFields.requiresApproval"),
            value: yesNo(Boolean(fn.requiresApproval)),
          },
          ...common.tail,
        ]}
      />
      {!toTable && (
        <ResponseColumns
          title={t("commandFormFields.outputColumnsTitle")}
          columns={fn.outputColumns ?? []}
          testId="function-read-columns"
        />
      )}
    </div>
  );
}

export function WebhookRead({ wh }: { wh: TrackedWebhook }) {
  const { t } = useTranslation();
  const common = useCommonFields(wh, "webhook");
  return (
    <div className="detail-groups" data-testid={`webhook-read-${wh.name}`}>
      <DetailFields
        testId="webhook-read-fields"
        fields={[
          ...common.head,
          {
            label: t("commandsPage.detailStatus"),
            value:
              wh.approved === false
                ? t("commandsPage.statusPending")
                : t("commandsPage.statusApproved"),
          },
          { label: t("commandFormFields.url"), value: wh.url },
          { label: t("commandFormFields.method"), value: wh.method },
          { label: t("commandFormFields.timeoutMs"), value: wh.timeoutMs },
          { label: t("commandFormFields.returnsTableOptional"), value: wh.returns },
          {
            label: t("commandFormFields.visibleTo"),
            value: roles(wh.visibleTo) ?? t("commandsPage.all"),
          },
          {
            label: t("commandFormFields.requiresApproval"),
            value: wh.requiresApproval ? t("commandsPage.yes") : t("commandsPage.no"),
          },
          ...common.tail,
        ]}
      />
      {!wh.returns && (
        <ResponseColumns
          title={t("commandFormFields.inlineReturnType")}
          columns={wh.inlineReturnType}
          testId="webhook-read-columns"
        />
      )}
    </div>
  );
}
