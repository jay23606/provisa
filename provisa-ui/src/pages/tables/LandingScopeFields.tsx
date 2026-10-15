// Copyright (c) 2026 Kenneth Stott
// Canary: 6bfb3966-7d70-4a56-8383-cfc5439b6c77
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "@mantine/core";
import type { RegisteredTable, Source } from "../../types/admin";
import { FormField } from "../../components/form/FormLayout";

/** Source types whose tables take arguments by name (a GraphQL root field's, an OpenAPI
 * operation's parameters): the only ones a table may fix them on. */
const ARGUMENT_SOURCE_TYPES = new Set(["graphql_remote", "openapi"]);

function argumentsText(args: Record<string, unknown> | null | undefined): string {
  return args && Object.keys(args).length > 0 ? JSON.stringify(args, null, 2) : "";
}

/** What of a table its replica holds: the landing filter, and, on a table of an API that takes
 * arguments by name, the arguments fixed for every read. */
export function LandingScopeFields({
  editingTable,
  setEditingTable,
  source,
}: {
  editingTable: RegisteredTable;
  setEditingTable: (t: RegisteredTable) => void;
  source?: Source;
}) {
  const { t } = useTranslation();
  const [argsText, setArgsText] = useState(() => argumentsText(editingTable.arguments));
  const [argsError, setArgsError] = useState<string | null>(null);
  const takesArguments = ARGUMENT_SOURCE_TYPES.has(source?.type ?? "");

  const onArguments = (text: string) => {
    setArgsText(text);
    if (!text.trim()) {
      setArgsError(null);
      setEditingTable({ ...editingTable, arguments: {} });
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setArgsError(t("landingScope.argumentsNotJson"));
      return;
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      setArgsError(t("landingScope.argumentsNotObject"));
      return;
    }
    setArgsError(null);
    setEditingTable({ ...editingTable, arguments: parsed as Record<string, unknown> });
  };

  return (
    <>
      <FormField size="long" help={t("landingScope.filterHelp")}>
        <Textarea
          label={t("landingScope.filterLabel")}
          placeholder={t("landingScope.filterPlaceholder")}
          autosize
          minRows={1}
          maxRows={4}
          styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }}
          value={editingTable.landingFilter ?? ""}
          onChange={(e) =>
            setEditingTable({ ...editingTable, landingFilter: e.target.value || null })
          }
          data-testid="landing-filter-input"
        />
      </FormField>
      {takesArguments && (
        <FormField size="long" help={t("landingScope.argumentsHelp")}>
          <Textarea
            label={t("landingScope.argumentsLabel")}
            placeholder={'{"owner": "acme"}'}
            autosize
            minRows={2}
            maxRows={8}
            styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }}
            value={argsText}
            error={argsError}
            onChange={(e) => onArguments(e.target.value)}
            data-testid="fixed-arguments-input"
          />
        </FormField>
      )}
    </>
  );
}
