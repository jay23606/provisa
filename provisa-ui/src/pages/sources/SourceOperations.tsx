// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useState } from "react";
import { Alert, Stack, Table, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { fetchActions, type TrackedFunction } from "../../api/actions";
import { ServiceNowApisSection } from "./ServiceNowApisSection";

/** A source's operations: the commands registered from it and, for ServiceNow, its APIs. */
export function SourceOperations({ sourceId, type }: { sourceId: string; type: string }) {
  const { t } = useTranslation();
  const [commands, setCommands] = useState<TrackedFunction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetchActions().then(
      (actions) => live && setCommands(actions.functions.filter((f) => f.sourceId === sourceId)),
      (e: unknown) => live && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      live = false;
    };
  }, [sourceId]);
  return (
    <Stack gap="md" data-testid="source-operations">
      {type === "servicenow" && <ServiceNowApisSection sourceId={sourceId} />}
      <div>
        <Text fw={700} c="dimmed" fz="0.75rem" tt="uppercase" mb="xs">
          {t("sourceSections.commands")}
        </Text>
        {error !== null ? (
          <Alert color="red">{error}</Alert>
        ) : commands === null ? null : commands.length === 0 ? (
          <Text size="sm" data-testid="source-commands-none">
            {t("detailFields.empty")}
          </Text>
        ) : (
          <Table className="data-table" data-testid="source-commands">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("sourceSections.commandName")}</Table.Th>
                <Table.Th>{t("sourceSections.commandKind")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {commands.map((c) => (
                <Table.Tr key={c.name}>
                  <Table.Td>{c.name}</Table.Td>
                  <Table.Td>{c.kind}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </div>
    </Stack>
  );
}
