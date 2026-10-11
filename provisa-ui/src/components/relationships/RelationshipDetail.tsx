// Copyright (c) 2026 Kenneth Stott
// Canary: 9c9d740c-8fca-47e8-ad1a-32409bac647d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A relationship's detail, shown in the page's right-hand panel: what it joins, or the form that
// edits it. Its actions sit in the panel's pinned head, out of use while the form is open.

import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "../ConfirmDialog";
import { FormChecks, FormField, FormFooter, FormLayout } from "../form/FormLayout";
import {
  ActionIcon,
  Checkbox,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  NumberInput,
} from "@mantine/core";
import { Trash2, Pencil, ArrowLeftRight } from "lucide-react";
import type { Relationship, RegisteredTable } from "../../types/admin";
import type { TrackedFunction } from "../../api/actions";
import type { RelForm } from "./relationship-types";
import { domainToSqlName } from "../../naming";
import { JunctionPanel } from "./JunctionPanel";
import { PanelActions } from "../list/SplitPane";
import { relationshipTargetLabel } from "./relationship-types";

interface RelationshipDetailProps {
  rel: Relationship;
  editingRel: RelForm | null;
  setEditingRel: (f: RelForm | null) => void;
  canManage: boolean;
  onStartEdit: () => void;
  /** Opens the form that creates this relationship's reverse. */
  onReverse: () => void;
  onDelete: () => void;
  onEditSave: () => void;
  saving: string | null;
  tables: RegisteredTable[];
  functions: TrackedFunction[];
  tableDomainById: Record<string, string>;
  domainsEnabled: boolean;
}

export function RelationshipDetail({
  rel: r,
  editingRel,
  setEditingRel,
  canManage,
  onStartEdit,
  onReverse,
  onDelete,
  onEditSave,
  saving,
  tables,
  functions,
  tableDomainById,
  domainsEnabled,
}: RelationshipDetailProps) {
  const { t } = useTranslation();
  const targetLabel = relationshipTargetLabel(r, tableDomainById, domainsEnabled);

  return (
    <>
      {canManage && (
        <PanelActions>
          <fieldset className="panel-action-set" disabled={editingRel !== null}>
            <Group gap="sm">
              <ActionIcon
                variant="subtle"
                aria-label={t("relationshipRow.edit")}
                title={t("relationshipRow.edit")}
                onClick={(e) => {
                  e.stopPropagation();
                  onStartEdit();
                }}
              >
                <Pencil size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label={t("relationshipRow.generateReverse")}
                title={t("relationshipRow.generateReverse")}
                onClick={(e) => {
                  e.stopPropagation();
                  onReverse();
                }}
              >
                <ArrowLeftRight size={14} />
              </ActionIcon>
              <ConfirmDialog
                title={t("relationshipRow.deleteTitle", { id: r.id })}
                consequence={t("relationshipRow.deleteConsequence")}
                onConfirm={onDelete}
              >
                {(open) => (
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={t("relationshipRow.delete")}
                    title={t("relationshipRow.delete")}
                    onClick={(e) => {
                      e.stopPropagation();
                      open();
                    }}
                  >
                    <Trash2 size={14} />
                  </ActionIcon>
                )}
              </ConfirmDialog>
            </Group>
          </fieldset>
        </PanelActions>
      )}
      {!editingRel ? (
        <Stack gap="sm">
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "max-content 1fr",
              gap: "0.25rem 1rem",
              margin: 0,
              color: "var(--text)",
            }}
          >
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.source")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>
              {`${r.sourceTableName}.${r.sourceColumn}`}
            </dd>
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.target")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>{targetLabel}</dd>
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.gqlAlias")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>
              <code>{r.graphqlAlias ?? t("relationshipRow.none")}</code>
            </dd>
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.cqlAlias")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>
              <code>
                {r.alias ?? (
                  <Text span c="dimmed" fs="italic">
                    {r.computedCypherAlias ?? t("relationshipRow.none")}
                  </Text>
                )}
              </code>
            </dd>
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.cardinality")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>{r.cardinality}</dd>
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.materialize")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>
              {r.materialize ? t("relationshipRow.yes") : t("relationshipRow.no")}
            </dd>
            {r.materialize && (
              <>
                <dt style={{ color: "var(--text-muted)" }}>
                  <strong>{t("relationshipRow.refreshIntervalSeconds")}</strong>
                </dt>
                <dd style={{ color: "var(--text)", margin: 0 }}>
                  {r.refreshInterval ?? t("relationshipRow.none")}
                </dd>
              </>
            )}
            <dt style={{ color: "var(--text-muted)" }}>
              <strong>{t("relationshipRow.cypherGraph")}</strong>
            </dt>
            <dd style={{ color: "var(--text)", margin: 0 }}>
              {r.disableCypher ? (
                <Text span c="dimmed" fs="italic">
                  {t("relationshipRow.excluded")}
                </Text>
              ) : (
                t("relationshipRow.included")
              )}
            </dd>
          </dl>
        </Stack>
      ) : (
        <FormLayout>
          <FormField size="medium">
            <TextInput
              label={t("relationshipRow.aliasLabel")}
              value={editingRel.alias}
              onChange={(e) => setEditingRel({ ...editingRel, alias: e.target.value })}
              placeholder={r.computedCypherAlias ?? "PLACED_BY"}
            />
          </FormField>
          <FormField size="medium">
            <TextInput
              label={t("relationshipRow.graphqlAliasLabel")}
              value={editingRel.graphqlAlias}
              onChange={(e) => setEditingRel({ ...editingRel, graphqlAlias: e.target.value })}
              placeholder={r.graphqlAlias ?? ""}
            />
          </FormField>
          {/* Source panel */}
          {(() => {
            const uniqueDomains = [
              ...new Set(tables.map((t2) => domainToSqlName(t2.domainId)).filter(Boolean)),
            ].sort();
            const filteredSrcTables = editingRel.sourceDomain
              ? tables.filter((t2) => domainToSqlName(t2.domainId) === editingRel.sourceDomain)
              : tables;
            return (
              <FormLayout aria-label={t("relationshipRow.source")}>
                <Text fw={700} c="dimmed" fz="0.75rem" tt="uppercase">
                  {t("relationshipRow.source")}
                </Text>
                {domainsEnabled && (
                  <FormField size="medium">
                    <Select
                      label={t("relationshipRow.domainLabel")}
                      data={[
                        { value: "", label: t("relationshipRow.domainAll") },
                        ...uniqueDomains.map((d) => ({ value: d, label: d })),
                      ]}
                      value={editingRel.sourceDomain}
                      onChange={(v) =>
                        setEditingRel({
                          ...editingRel,
                          sourceDomain: v ?? "",
                          sourceTableId: "",
                        })
                      }
                      allowDeselect={false}
                    />
                  </FormField>
                )}
                <FormField size="medium">
                  <Select
                    label={t("relationshipRow.tableLabel")}
                    data={[
                      { value: "", label: t("relationshipRow.selectPlaceholder") },
                      ...filteredSrcTables.map((t2) => ({
                        value: t2.tableName,
                        label: t2.tableName,
                      })),
                    ]}
                    value={editingRel.sourceTableId}
                    onChange={(v) => setEditingRel({ ...editingRel, sourceTableId: v ?? "" })}
                    allowDeselect={false}
                  />
                </FormField>
                <FormField size="medium">
                  <Select
                    label={t("relationshipRow.columnLabel")}
                    data={[
                      { value: "", label: t("relationshipRow.selectPlaceholder") },
                      ...(
                        tables.find((t2) => t2.tableName === editingRel.sourceTableId)?.columns ??
                        []
                      ).map((c) => ({ value: c.columnName, label: c.columnName })),
                    ]}
                    value={editingRel.sourceColumn}
                    onChange={(v) => setEditingRel({ ...editingRel, sourceColumn: v ?? "" })}
                    allowDeselect={false}
                  />
                </FormField>
              </FormLayout>
            );
          })()}
          {/* Target panel */}
          <FormLayout aria-label={t("relationshipRow.target")}>
            <Text fw={700} c="dimmed" fz="0.75rem" tt="uppercase">
              {t("relationshipRow.target")}
            </Text>
            <FormField size="medium">
              <Select
                label={t("relationshipRow.targetTypeLabel")}
                data={[
                  { value: "table", label: t("relationshipRow.targetTypeTable") },
                  { value: "function", label: t("relationshipRow.targetTypeFunction") },
                ]}
                value={editingRel.targetType}
                onChange={(v) =>
                  setEditingRel({
                    ...editingRel,
                    targetType: (v ?? "table") as "table" | "function",
                    targetTableId: "",
                    targetColumn: "",
                    targetFunctionName: "",
                    functionArg: "",
                  })
                }
                allowDeselect={false}
              />
            </FormField>
            {editingRel.targetType === "table" ? (
              (() => {
                const uniqueDomains = [
                  ...new Set(tables.map((t2) => domainToSqlName(t2.domainId)).filter(Boolean)),
                ].sort();
                const filteredTgtTables = editingRel.targetDomain
                  ? tables.filter((t2) => domainToSqlName(t2.domainId) === editingRel.targetDomain)
                  : tables;
                return (
                  <>
                    {domainsEnabled && (
                      <FormField size="medium">
                        <Select
                          label={t("relationshipRow.domainLabel")}
                          data={[
                            { value: "", label: t("relationshipRow.domainAll") },
                            ...uniqueDomains.map((d) => ({ value: d, label: d })),
                          ]}
                          value={editingRel.targetDomain}
                          onChange={(v) =>
                            setEditingRel({
                              ...editingRel,
                              targetDomain: v ?? "",
                              targetTableId: "",
                            })
                          }
                          allowDeselect={false}
                        />
                      </FormField>
                    )}
                    <FormField size="medium">
                      <Select
                        label={t("relationshipRow.tableLabel")}
                        data={[
                          { value: "", label: t("relationshipRow.selectPlaceholder") },
                          ...filteredTgtTables.map((t2) => ({
                            value: t2.tableName,
                            label: t2.tableName,
                          })),
                        ]}
                        value={editingRel.targetTableId}
                        onChange={(v) => setEditingRel({ ...editingRel, targetTableId: v ?? "" })}
                        allowDeselect={false}
                      />
                    </FormField>
                    <FormField size="medium">
                      <Select
                        label={t("relationshipRow.columnLabel")}
                        data={[
                          { value: "", label: t("relationshipRow.selectPlaceholder") },
                          ...(
                            tables.find((t2) => t2.tableName === editingRel.targetTableId)
                              ?.columns ?? []
                          ).map((c) => ({ value: c.columnName, label: c.columnName })),
                        ]}
                        value={editingRel.targetColumn}
                        onChange={(v) => setEditingRel({ ...editingRel, targetColumn: v ?? "" })}
                        allowDeselect={false}
                      />
                    </FormField>
                  </>
                );
              })()
            ) : (
              <>
                <FormField size="medium">
                  <Select
                    label={t("relationshipRow.functionLabel")}
                    data={[
                      { value: "", label: t("relationshipRow.selectPlaceholder") },
                      ...functions.map((f) => ({ value: f.name, label: f.name })),
                    ]}
                    value={editingRel.targetFunctionName}
                    onChange={(v) => setEditingRel({ ...editingRel, targetFunctionName: v ?? "" })}
                    allowDeselect={false}
                  />
                </FormField>
                <FormField size="medium">
                  <TextInput
                    label={t("relationshipRow.functionArgLabel")}
                    value={editingRel.functionArg}
                    onChange={(e) => setEditingRel({ ...editingRel, functionArg: e.target.value })}
                    placeholder={t("relationshipRow.functionArgPlaceholder")}
                  />
                </FormField>
              </>
            )}
          </FormLayout>
          {editingRel.targetType === "table" && (
            <FormField size="medium">
              <Select
                label={t("relationshipRow.cardinality")}
                data={[
                  { value: "many-to-one", label: t("relationshipRow.cardinalityManyToOne") },
                  { value: "one-to-many", label: t("relationshipRow.cardinalityOneToMany") },
                ]}
                value={editingRel.cardinality}
                onChange={(v) => setEditingRel({ ...editingRel, cardinality: v ?? "many-to-one" })}
                allowDeselect={false}
              />
            </FormField>
          )}
          <FormChecks>
            <FormField size="short">
              <Checkbox
                label={t("relationshipRow.materializeCheckbox")}
                checked={editingRel.materialize}
                onChange={(e) =>
                  setEditingRel({ ...editingRel, materialize: e.currentTarget.checked })
                }
              />
            </FormField>
            <FormField size="short">
              <Checkbox
                label={t("relationshipRow.excludeFromCypher")}
                checked={editingRel.disableCypher}
                onChange={(e) =>
                  setEditingRel({ ...editingRel, disableCypher: e.currentTarget.checked })
                }
              />
            </FormField>
          </FormChecks>
          {editingRel.materialize && (
            <FormField size="short">
              <NumberInput
                label={t("relationshipRow.refreshIntervalSeconds")}
                value={editingRel.refreshInterval}
                onChange={(v) => setEditingRel({ ...editingRel, refreshInterval: String(v) })}
              />
            </FormField>
          )}
          {editingRel.targetType === "table" && editingRel.cardinality === "many-to-one" && (
            <FormField size="full">
              <Text c="orange.7" fz="0.78rem">
                {t("relationshipRow.cardinalityWarning")}
              </Text>
            </FormField>
          )}
          {editingRel.targetType === "table" && (
            <FormField size="full">
              <JunctionPanel
                form={editingRel}
                setForm={setEditingRel}
                tables={tables}
                testIdPrefix="rel-edit"
              />
            </FormField>
          )}
          <FormFooter onSave={onEditSave} saving={!!saving} onCancel={() => setEditingRel(null)} />
        </FormLayout>
      )}
    </>
  );
}
