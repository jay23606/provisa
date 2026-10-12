// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1954: the APIs a ServiceNow instance publishes, under their namespaces, each switched on or
// off in place in its row: switched on, it is offered through the source's companion OpenAPI
// source.

import { Stack, Switch, Text } from "@mantine/core";

export interface InstanceApi {
  namespace: string;
  name: string;
  route: string;
  description: string;
  scripted: boolean;
  added: boolean;
}

export function ServiceNowApiList({
  groups,
  onSwitch,
}: {
  groups: [string, InstanceApi[]][];
  onSwitch: (api: InstanceApi, added: boolean) => void;
}) {
  return (
    <div style={{ maxHeight: 320, overflowY: "auto" }}>
      {groups.map(([namespace, apis]) => (
        <Stack key={namespace} gap={4} mb="xs">
          <Text size="xs" c="dimmed" fw={600}>
            {namespace}
          </Text>
          {apis.map((api) => (
            <Switch
              key={api.name}
              size="xs"
              checked={api.added}
              label={`${api.name} (${api.route})`}
              data-testid={`servicenow-api-${api.route}`}
              onChange={(e) => onSwitch(api, e.currentTarget.checked)}
            />
          ))}
        </Stack>
      ))}
    </div>
  );
}
