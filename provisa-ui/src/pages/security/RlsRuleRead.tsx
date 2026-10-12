// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useTranslation } from "react-i18next";
import { Text } from "@mantine/core";
import type { RLSRule } from "../../types/admin";
import { DetailFields } from "../../components/detail/DetailFields";

/**
 * Every value of an RLS rule, read-only, under the labels its form gives them: what it applies
 * to and the domain that is in, the table or action it names, the role it limits and its filter.
 */
export function RlsRuleRead({
  rule: r,
  domain,
  tableLabel,
}: {
  rule: RLSRule;
  /** The domain the form shows for the rule: its own, its table's or its action's. */
  domain: string | null;
  /** The rule's table as the list names it; null for a rule on a domain or an action. */
  tableLabel: string | null;
}) {
  const { t } = useTranslation();
  const scope = r.actionName ? "action" : r.domainId ? "domain" : "table";
  const scopeLabel = {
    table: t("securityPage.applyToTable"),
    domain: t("securityPage.applyToDomain"),
    action: t("securityPage.applyToAction"),
  }[scope];
  return (
    <DetailFields
      testId={`rule-read-${r.id}`}
      fields={[
        { label: t("securityPage.ruleId"), value: String(r.id) },
        { label: t("securityPage.applyTo"), value: scopeLabel },
        { label: t("securityPage.domain"), value: domain },
        ...(scope === "action"
          ? [{ label: t("securityPage.action"), value: r.actionName }]
          : scope === "table"
            ? [{ label: t("securityPage.table"), value: tableLabel }]
            : []),
        { label: t("securityPage.role"), value: r.roleId },
        {
          label: t("securityPage.filterExpression"),
          value: (
            <Text component="code" span>
              {r.filterExpr}
            </Text>
          ),
        },
      ]}
    />
  );
}
