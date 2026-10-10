// Copyright (c) 2026 Kenneth Stott
// Canary: 7c2e9a41-5b8d-4f36-a1e0-3d9f6b2c8e57
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1907: per-role staleness tolerance on a table. The operator lists role → TTL (seconds); a
// reader's effective TTL is always max(cache_ttl, role_ttl(role)), where cache_ttl is the table's
// resolved TTL (table, else source, else global) and is the operator's floor.

import { useTranslation } from "react-i18next";
import { Button, NumberInput, Select, Text } from "@mantine/core";
import { X } from "lucide-react";
import type { RoleTtl } from "../../types/admin";
import type { Role } from "../../types/auth";
import { FieldLabel } from "./FieldLabel";
import { roleTtlRowError } from "./roleTtl";
import { FieldGroup, FormField, FormLayout } from "../../components/form/FormLayout";

interface RoleTtlFieldProps {
  rows: RoleTtl[];
  onChange: (rows: RoleTtl[]) => void;
  roles: Role[];
  // The table's resolved landing cache_ttl — the staged table value, else the source's (REQ-930;
  // the global default is the response-cache TTL, not a landing clock). null when neither sets one:
  // the floor is then 0, so a role's effective TTL is its own entry.
  floorTtl: number | null;
}

export function RoleTtlField({ rows, onChange, roles, floorTtl }: RoleTtlFieldProps) {
  const { t } = useTranslation();
  const listed = new Set(rows.map((r) => r.role));
  const unlisted = roles.filter((r) => !listed.has(r.id));

  const update = (index: number, patch: Partial<RoleTtl>) =>
    onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));

  return (
    <FormLayout data-testid="role-ttl-field">
      <FormField size="full">
        <FieldLabel text={t("tableEditForm.roleTtlLabel")} help={t("tableEditForm.roleTtlHelp")} />
      </FormField>
      {rows.map((row, i) => {
        const error = roleTtlRowError(rows, i);
        // A role may pick itself or any role not already listed — never a duplicate.
        const options = roles
          .filter((r) => r.id === row.role || !listed.has(r.id))
          .map((r) => ({ value: r.id, label: r.id }));
        return (
          <FormField size="full" key={i} data-testid="role-ttl-row">
            <FormLayout>
              <FieldGroup row>
                <FormField size="medium">
                  <Select
                    aria-label={t("tableEditForm.roleTtlRole")}
                    data={options}
                    value={row.role}
                    onChange={(v) => v != null && update(i, { role: v })}
                    allowDeselect={false}
                    comboboxProps={{ withinPortal: true }}
                  />
                </FormField>
                <FormField size="short">
                  <NumberInput
                    aria-label={t("tableEditForm.roleTtlSeconds")}
                    min={0}
                    allowDecimal={false}
                    allowNegative={false}
                    value={Number.isNaN(row.ttl) ? "" : row.ttl}
                    onChange={(v) => update(i, { ttl: v === "" ? Number.NaN : Number(v) })}
                    error={error ? t(error) : undefined}
                  />
                </FormField>
                <Button
                  variant="subtle"
                  color="red"
                  aria-label={t("tableEditForm.roleTtlRemove", { role: row.role })}
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}
                >
                  <X size={14} />
                </Button>
              </FieldGroup>
            </FormLayout>
            {error === null && (
              <Text size="xs" c="dimmed" data-testid="role-ttl-effective">
                {t("tableEditForm.roleTtlEffective", { sec: Math.max(floorTtl ?? 0, row.ttl) })}
                {floorTtl !== null && row.ttl < floorTtl && (
                  <Text span size="xs" c="var(--warning, #d19a00)" data-testid="role-ttl-no-effect">
                    {" "}
                    {t("tableEditForm.roleTtlBelowFloor", { floor: floorTtl })}
                  </Text>
                )}
              </Text>
            )}
          </FormField>
        );
      })}
      <FormField size="full">
        <Button
          variant="light"
          size="xs"
          mt={4}
          disabled={unlisted.length === 0}
          onClick={() => onChange([...rows, { role: unlisted[0].id, ttl: floorTtl ?? 0 }])}
        >
          {t("tableEditForm.roleTtlAdd")}
        </Button>
      </FormField>
      {floorTtl !== null && (
        <FormField size="full">
          <Text size="xs" c="dimmed" data-testid="role-ttl-unlisted">
            {t("tableEditForm.roleTtlUnlisted", { sec: floorTtl })}
          </Text>
        </FormField>
      )}
    </FormLayout>
  );
}
