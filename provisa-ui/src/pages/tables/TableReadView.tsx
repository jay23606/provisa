// Copyright (c) 2026 Kenneth Stott
// Canary: 2b6d9e47-3f1a-4c8b-a5e2-7d0f4c9b2e65
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Trash2, Pencil } from "lucide-react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import type { NavigateFunction } from "react-router-dom";
import type { RegisteredTable, DataProduct } from "../../types/admin";
import type { ReplicaBuild } from "../../api/admin";
import { ReplicatingMark } from "./ReplicatingMark";
import { computeProfile } from "./helpers";
import { TagControl } from "../../components/TagControl";
import { ColumnGlossaryHover } from "./ColumnGlossaryHover";
import { OwnerResolutionIcon } from "../../components/OwnerResolution";
import { LatestProfilePanel } from "./LatestProfilePanel";
import { PanelActions } from "../../components/list/SplitPane";
import { ColumnTabs } from "./ColumnTabs";
import { useColumnTab } from "./columnTopics";
import { toIrType } from "../../irTypes";

interface TableProfileResult {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
}

interface TableReadViewProps {
  t: RegisteredTable;
  /** The table's replica build as last reported; undefined when it has none. */
  build?: ReplicaBuild;
  dataProducts: DataProduct[]; // REQ-1634
  navigate: NavigateFunction;
  viewsOnly: boolean;
  deploying: Record<number, boolean>;
  setDeploying: React.Dispatch<React.SetStateAction<Record<number, boolean>>>;
  deployMsg: Record<number, { success: boolean; message: string }>;
  setDeployMsg: React.Dispatch<
    React.SetStateAction<Record<number, { success: boolean; message: string }>>
  >;
  tableProfiles: Record<number, TableProfileResult | "loading" | string>;
  deployViewToDb: (id: number) => Promise<{ success: boolean; message: string }>;
  reload: () => void;
  startEditing: (t: RegisteredTable) => void;
  handleDelete: (id: number) => void;
  handleProfile: (id: number) => void;
  /** REQ-1944: a governance-only viewer: no registration, deploy, profiling or delete. */
  hidingOnly?: boolean;
  // REQ-1921: put the table out of service (draft) or release it. The view shows the stored
  // state: the box follows `table.draft` once the change is saved and the table reloaded.
  onSetDraft?: (table: RegisteredTable, draft: boolean) => void;
  // REQ-1386: opens the governed SELECT * preview modal.
  onPreview: (t: RegisteredTable) => void;
  // REQ-1318: opens the Views-page definition-mode editor (SQL | Metrics toggle).
  onEditDefinition?: (t: RegisteredTable) => void;
  // REQ-1934: the table's registered profile columns table, when one is registered.
  profileColumnsTable?: RegisteredTable | null;
  /** Render the action row alone: the edit form shows it, disabled, in the panel's head. */
  actionsOnly?: boolean;
  actionsDisabled?: boolean;
}

export function TableReadView({
  t: table,
  build,
  dataProducts,
  navigate,
  viewsOnly,
  deploying,
  setDeploying,
  deployMsg,
  setDeployMsg,
  tableProfiles,
  deployViewToDb,
  reload,
  startEditing,
  handleDelete,
  handleProfile,
  hidingOnly = false,
  onSetDraft,
  onPreview,
  onEditDefinition,
  profileColumnsTable,
  actionsOnly = false,
  actionsDisabled = false,
}: TableReadViewProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useColumnTab();

  // The table's actions. In a detail panel they sit in its pinned head (PanelActions); under a
  // list row they stay in place. While the table is being edited they are shown but cannot be
  // used: each of them would leave the form.
  const actions = (
    <PanelActions>
      <fieldset className="panel-action-set" disabled={actionsDisabled}>
        <Group justify="flex-start" p="0.5rem" gap="0.5rem" wrap="wrap">
          <ReplicatingMark build={build} size="detail" />
          {table.viewSql && (
            <Button
              size="compact-sm"
              variant="default"
              data-testid="table-read-view-edit-sql"
              onClick={(e) => {
                e.stopPropagation();
                navigate("/sql", { state: { sql: table.viewSql, viewTable: table } });
              }}
              title={t("tableReadView.editSqlTitle")}
            >
              {viewsOnly
                ? t("tableReadView.editSqlButton")
                : t("tableReadView.openInExplorerButton")}
            </Button>
          )}
          {table.viewSql && onEditDefinition && !hidingOnly && (
            <Button
              size="compact-sm"
              variant="default"
              data-testid="table-read-view-edit-definition"
              onClick={(e) => {
                e.stopPropagation();
                onEditDefinition(table);
              }}
              title={t("tableReadView.editDefinitionTitle")}
            >
              {t("tableReadView.editDefinitionButton")}
            </Button>
          )}
          {table.canDeployToDb && !hidingOnly && (
            <Button
              size="compact-sm"
              variant="default"
              data-testid="table-read-view-deploy"
              onClick={async (e) => {
                e.stopPropagation();
                setDeploying((prev) => ({ ...prev, [table.id]: true }));
                setDeployMsg((prev) => {
                  const next = { ...prev };
                  delete next[table.id];
                  return next;
                });
                const result = await deployViewToDb(table.id);
                setDeploying((prev) => ({ ...prev, [table.id]: false }));
                setDeployMsg((prev) => ({ ...prev, [table.id]: result }));
                if (result.success) reload();
              }}
              title={t("tableReadView.deployToDbTitle")}
              disabled={deploying[table.id]}
            >
              {deploying[table.id]
                ? t("tableReadView.deployingButton")
                : t("tableReadView.deployToDbButton")}
            </Button>
          )}
          {/* A table that needs a value for a required parameter is asked for it first: Preview
              in its own viewer, Profile in the dialog its handler opens. */}
          <Button
            size="compact-sm"
            variant="default"
            data-testid="table-read-view-preview"
            onClick={(e) => {
              e.stopPropagation();
              onPreview(table);
            }}
            title={t("tableReadView.previewTitle")}
          >
            {t("tableReadView.previewButton")}
          </Button>
          {!hidingOnly && (
            <Button
              size="compact-sm"
              variant="default"
              data-testid="table-read-view-profile"
              onClick={(e) => {
                e.stopPropagation();
                handleProfile(table.id);
              }}
              title={t("tableReadView.profileTitle")}
              disabled={tableProfiles[table.id] === "loading"}
            >
              {tableProfiles[table.id] === "loading"
                ? t("tableReadView.profilingButton")
                : t("tableReadView.profileButton")}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            data-testid="table-read-view-policies"
            title={t("tableReadView.policiesTitle")}
            onClick={(e) => {
              e.stopPropagation();
              navigate("/security/rls", {
                state: { tableFilter: table.tableName },
              });
            }}
          >
            {t("tableReadView.policiesButton")}
          </Button>
          {/* REQ-1958: the editor opens for a caller who is not shown the grant lists and masks
              too; it shows none of them and its save names none, so the store keeps them. */}
          <ActionIcon
            variant="subtle"
            aria-label={t("tableReadView.editButtonLabel", { name: table.tableName })}
            data-testid="table-read-view-edit"
            onClick={(e) => {
              e.stopPropagation();
              startEditing(table);
            }}
          >
            <Pencil size={14} />
          </ActionIcon>
          {!hidingOnly && (
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={t("tableReadView.deleteButtonLabel", { name: table.tableName })}
              data-testid="table-read-view-delete"
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(table.id);
              }}
            >
              <Trash2 size={14} />
            </ActionIcon>
          )}
          {/* REQ-1921: draft is set and cleared here, beside the table's other actions. It needs
              the right to register tables in the table's domain; without it the box only shows
              the state. */}
          <Tooltip
            label={
              hidingOnly || !onSetDraft
                ? t("tableReadView.draftNoRightTooltip")
                : t("tableReadView.draftTooltip")
            }
            withArrow
          >
            <Checkbox
              size="xs"
              label={t("tableReadView.draftLabel")}
              checked={table.draft}
              disabled={hidingOnly || !onSetDraft}
              data-testid="table-read-view-draft"
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onSetDraft?.(table, e.currentTarget.checked)}
            />
          </Tooltip>
        </Group>
      </fieldset>
    </PanelActions>
  );
  if (actionsOnly) return actions;

  return (
    <>
      {table.description && (
        <Box
          px="0.75rem"
          py="0.5rem"
          fz="0.85rem"
          c="dimmed"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          {table.description}
        </Box>
      )}
      {/* The same three topics as the column editor: the name first, a tab's attributes after. */}
      <ColumnTabs value={tab} onChange={setTab} />
      <Table.ScrollContainer minWidth={480}>
        <Table className="data-table" style={{ margin: 0 }}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("tableReadView.colColumn")}</Table.Th>
              {tab === "naming" && (
                <>
                  <Table.Th>{t("tableReadView.colSqlAlias")}</Table.Th>
                  <Table.Th w="60%">{t("tableReadView.colDescription")}</Table.Th>
                </>
              )}
              {tab === "type" && (
                <>
                  <Table.Th>{t("tableEditForm.dataTypeHeader")}</Table.Th>
                  <Table.Th>{t("tableReadView.colPk")}</Table.Th>
                  <Table.Th>{t("tableReadView.colScope")}</Table.Th>
                </>
              )}
              {tab === "access" && (
                <>
                  <Table.Th>{t("tableReadView.colVisibleTo")}</Table.Th>
                  <Table.Th>{t("tableReadView.colWritableBy")}</Table.Th>
                  <Table.Th>{t("tableReadView.colMasking")}</Table.Th>
                </>
              )}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {table.columns.map((c) => (
              <Fragment key={c.id}>
                <Table.Tr>
                  <Table.Td>
                    {/* REQ-1387: glossary term summary card on column-name hover. */}
                    <ColumnGlossaryHover
                      tableId={table.id}
                      columnName={c.columnName}
                      // Every attribute of the column, whichever tab shows it.
                      definition={[
                        { label: t("tableReadView.colColumn"), value: c.columnName },
                        { label: t("tableReadView.colSqlAlias"), value: c.computedSqlAlias || "" },
                        { label: t("tableReadView.colDescription"), value: c.description || "" },
                        {
                          label: t("tableEditForm.dataTypeHeader"),
                          value: c.dataType ? toIrType(c.dataType) : "",
                        },
                        { label: t("tableReadView.colPk"), value: c.isPrimaryKey ? "✓" : "" },
                        {
                          label: t("tableReadView.colScope"),
                          value: c.scope || t("tableReadView.scopeDomain"),
                        },
                        {
                          label: t("tableReadView.colVisibleTo"),
                          value: c.visibleTo === null ? "" : c.visibleTo.join(", "),
                        },
                        {
                          label: t("tableReadView.colWritableBy"),
                          value: c.writableBy === null ? "" : c.writableBy.join(", "),
                        },
                        { label: t("tableReadView.colMasking"), value: c.maskType || "" },
                      ]}
                    >
                      <code>{c.columnName}</code>
                    </ColumnGlossaryHover>
                    {c.nativeFilterType && (
                      <Badge
                        ml="0.4rem"
                        size="xs"
                        variant="light"
                        color={c.nativeFilterType === "path_param" ? "yellow" : "blue"}
                        style={{ fontFamily: "monospace" }}
                      >
                        {c.nativeFilterType === "path_param"
                          ? t("tableReadView.pathBadge")
                          : t("tableReadView.queryBadge")}
                      </Badge>
                    )}
                    {c.isForeignKey && (
                      <Badge
                        ml="0.4rem"
                        size="xs"
                        variant="light"
                        color="green"
                        style={{ fontFamily: "monospace" }}
                      >
                        {t("tableReadView.fkBadge")}
                      </Badge>
                    )}
                    {c.isAlternateKey && (
                      <Badge
                        ml="0.4rem"
                        size="xs"
                        variant="light"
                        color="yellow"
                        style={{ fontFamily: "monospace" }}
                      >
                        {t("tableReadView.akBadge")}
                      </Badge>
                    )}{" "}
                    <TagControl objectType="column" tableId={table.id} columnName={c.columnName} />
                  </Table.Td>
                  {tab === "naming" && (
                    <>
                      <Table.Td c={c.alias ? "white" : "dimmed"}>{c.computedSqlAlias}</Table.Td>
                      <Table.Td className="reasoning-cell">{c.description || ""}</Table.Td>
                    </>
                  )}
                  {tab === "type" && (
                    <>
                      <Table.Td ff="monospace">{c.dataType ? toIrType(c.dataType) : ""}</Table.Td>
                      <Table.Td ta="center">
                        {c.isPrimaryKey && (
                          <Text span c="blue">
                            &#10003;
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>{c.scope || t("tableReadView.scopeDomain")}</Table.Td>
                    </>
                  )}
                  {tab === "access" && (
                    <>
                      {/* REQ-1958/REQ-1134: null grant lists are withheld (the caller lacks
                          view_governance), which is said — never shown as "all" or "none". */}
                      <Table.Td>
                        {c.visibleTo === null ? (
                          <Text span size="sm" c="dimmed" data-testid="grants-not-shown">
                            {t("tableReadView.notShown")}
                          </Text>
                        ) : (
                          <Group gap={4} wrap="nowrap">
                            <Text span size="sm">
                              {c.visibleTo.length > 0
                                ? c.visibleTo.join(", ")
                                : t("tableReadView.all")}
                            </Text>
                            {c.visibleTo.length > 0 && (
                              <OwnerResolutionIcon
                                refs={c.visibleTo}
                                ariaLabel={t("ownerResolution.columnIconLabel")}
                              />
                            )}
                          </Group>
                        )}
                      </Table.Td>
                      <Table.Td c={c.writableBy === null ? "dimmed" : undefined}>
                        {c.writableBy === null
                          ? t("tableReadView.notShown")
                          : c.writableBy.length > 0
                            ? c.writableBy.join(", ")
                            : t("tableReadView.none")}
                      </Table.Td>
                      <Table.Td c={c.visibleTo === null ? "dimmed" : undefined}>
                        {c.visibleTo === null
                          ? t("tableReadView.notShown")
                          : c.maskType || t("tableReadView.maskNone")}
                      </Table.Td>
                    </>
                  )}
                </Table.Tr>
                {tab === "access" && c.maskType && (
                  <Table.Tr>
                    <Table.Td colSpan={2} c="dimmed" fz="0.75rem" pl="1.5rem">
                      ↳{" "}
                      {c.maskType === "regex"
                        ? t("tableReadView.maskRegex", {
                            pattern: c.maskPattern,
                            replace: c.maskReplace,
                          })
                        : c.maskType === "constant"
                          ? t("tableReadView.maskConstant", {
                              value: c.maskValue ?? t("tableReadView.maskConstantNull"),
                            })
                          : t("tableReadView.maskTruncate", { precision: c.maskPrecision })}
                    </Table.Td>
                    <Table.Td colSpan={2} c="dimmed" fz="0.75rem">
                      {t("tableReadView.unmaskedTo", {
                        list:
                          c.unmaskedTo !== null && c.unmaskedTo.length > 0
                            ? c.unmaskedTo.join(", ")
                            : t("tableReadView.none"),
                      })}
                    </Table.Td>
                  </Table.Tr>
                )}
              </Fragment>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {table.apiEndpoint && (
        <Box px="0.75rem" py="0.5rem" fz="0.85rem" c="dimmed">
          {t("tableReadView.apiEndpoint")} <code>{table.apiEndpoint}</code>
        </Box>
      )}
      {table.watermarkColumn && (
        <Box px="0.75rem" py="0.5rem" fz="0.85rem" c="dimmed">
          {t("tableReadView.watermarkColumn")} <code>{table.watermarkColumn}</code>
        </Box>
      )}
      {table.queryTemplate && (
        <Box px="0.75rem" py="0.5rem" fz="0.85rem" data-testid="table-read-view-query-template">
          <Text span c="dimmed" mr="0.5rem">
            {t("tableReadView.queryTemplate")}
          </Text>
          <code style={{ fontSize: "0.78rem", wordBreak: "break-all" }}>
            {table.queryTemplate.length > 120
              ? table.queryTemplate.slice(0, 120) + "…"
              : table.queryTemplate}
          </code>
        </Box>
      )}
      {table.viewSql && (
        <Box px="0.75rem" py="0.5rem" fz="0.85rem">
          <Text span c="dimmed" mr="0.5rem">
            {t("tableReadView.viewSql")}
          </Text>
          <code style={{ fontSize: "0.78rem", wordBreak: "break-all" }}>
            {table.viewSql.length > 120 ? table.viewSql.slice(0, 120) + "…" : table.viewSql}
          </code>
        </Box>
      )}
      {/* Only what departs from the default is shown: a read-only table with no data product shows
          no chip at all. */}
      {(table.writeOps.length > 0 || table.productId != null) && (
        <Group px="0.75rem" py="0.5rem" gap="0.4rem" data-testid="table-read-view-chips">
          {table.writeOps.length > 0 && (
            <Tooltip
              label={t("tableReadView.writableOps", {
                ops: table.writeOps.map((op) => op.toUpperCase()).join(", "),
              })}
              withArrow
            >
              <Badge
                variant="light"
                size="sm"
                data-testid="table-read-view-writable"
                aria-label={t("tableReadView.writableOps", {
                  ops: table.writeOps.map((op) => op.toUpperCase()).join(", "),
                })}
              >
                {t("tableReadView.writable")}
              </Badge>
            </Tooltip>
          )}
          {table.productId != null && (
            <Tooltip label={t("tableReadView.dataProductChip")} withArrow>
              <Badge variant="light" color="green" size="sm" data-testid="table-read-view-product">
                {dataProducts.find((p) => p.id === table.productId)?.name ?? table.productId}
              </Badge>
            </Tooltip>
          )}
        </Group>
      )}
      {actions}
      {table.draft && (
        <Text
          size="xs"
          c="dimmed"
          px="0.5rem"
          pb="0.25rem"
          data-testid="table-read-view-draft-note"
        >
          {t("tableReadView.draftPreviewNote")}
        </Text>
      )}
      {deployMsg[table.id] && (
        <Box
          px="0.75rem"
          py="0.5rem"
          fz="0.8rem"
          c={deployMsg[table.id].success ? "var(--color-success, #22c55e)" : "var(--destructive)"}
        >
          {deployMsg[table.id].message}
        </Box>
      )}
      {profileColumnsTable && <LatestProfilePanel profileTable={profileColumnsTable} />}
      {(() => {
        const p = tableProfiles[table.id];
        if (!p || p === "loading") return null;
        if (typeof p === "string")
          return (
            <Box px="0.75rem" py="0.5rem" c="var(--destructive)" fz="0.8rem">
              {p}
            </Box>
          );
        const prof = computeProfile(p.columns, p.rows);
        return (
          <Box style={{ borderTop: "1px solid var(--border)" }} px="0.75rem" py="0.5rem">
            <Box fz="0.75rem" c="dimmed" mb="0.4rem">
              {t("tableReadView.profileHeading", { count: p.rowCount })}
            </Box>
            <Table.ScrollContainer minWidth={640}>
              <Table className="data-table" style={{ fontSize: "0.72rem" }}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t("tableReadView.colColumn")}</Table.Th>
                    <Table.Th title={t("tableReadView.colNullsTitle")}>
                      {t("tableReadView.colNulls")}
                    </Table.Th>
                    <Table.Th title={t("tableReadView.colBlanksTitle")}>
                      {t("tableReadView.colBlanks")}
                    </Table.Th>
                    <Table.Th title={t("tableReadView.colDistinctTitle")}>
                      {t("tableReadView.colDistinct")}
                    </Table.Th>
                    <Table.Th>{t("tableReadView.colMin")}</Table.Th>
                    <Table.Th>{t("tableReadView.colMax")}</Table.Th>
                    <Table.Th>{t("tableReadView.colMean")}</Table.Th>
                    <Table.Th>{t("tableReadView.colTopValues")}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {prof.map((c) => {
                    const nullPct =
                      p.rowCount > 0 ? Math.round((c.nullCount / p.rowCount) * 100) : 0;
                    const isHighNull = nullPct >= 50;
                    return (
                      <Table.Tr key={c.col}>
                        <Table.Td style={{ fontFamily: "monospace", fontWeight: 600 }}>
                          {c.col}
                        </Table.Td>
                        <Table.Td>
                          <Group gap="0.4rem" wrap="nowrap">
                            <Box
                              style={{
                                width: 52,
                                height: 5,
                                borderRadius: 3,
                                background: "var(--border)",
                                position: "relative",
                                flexShrink: 0,
                              }}
                            >
                              {c.nullCount > 0 && (
                                <Box
                                  style={{
                                    position: "absolute",
                                    left: 0,
                                    top: 0,
                                    bottom: 0,
                                    width: `${nullPct}%`,
                                    borderRadius: 3,
                                    background: isHighNull
                                      ? "var(--destructive)"
                                      : "var(--text-muted)",
                                  }}
                                />
                              )}
                            </Box>
                            <Text
                              span
                              fz="0.7rem"
                              c={
                                isHighNull
                                  ? "var(--destructive)"
                                  : c.nullCount > 0
                                    ? undefined
                                    : "dimmed"
                              }
                            >
                              {c.nullCount > 0 ? `${nullPct}%` : "—"}
                            </Text>
                          </Group>
                        </Table.Td>
                        <Table.Td c={c.blankCount > 0 ? undefined : "dimmed"}>
                          {c.blankCount > 0 ? c.blankCount : "—"}
                        </Table.Td>
                        <Table.Td>{c.distinctCount}</Table.Td>
                        <Table.Td style={{ fontFamily: "monospace" }}>
                          {c.min !== null ? String(c.min).slice(0, 16) : "—"}
                        </Table.Td>
                        <Table.Td style={{ fontFamily: "monospace" }}>
                          {c.max !== null ? String(c.max).slice(0, 16) : "—"}
                        </Table.Td>
                        <Table.Td style={{ fontFamily: "monospace" }}>
                          {c.mean !== null ? c.mean.toFixed(2) : "—"}
                        </Table.Td>
                        <Table.Td>
                          <Box
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: "0.18rem",
                              minWidth: 140,
                            }}
                          >
                            {c.topValues.map(({ value, count }) => {
                              const barPct =
                                c.topValues[0].count > 0 ? (count / c.topValues[0].count) * 100 : 0;
                              return (
                                <Group key={value} gap="0.3rem" wrap="nowrap">
                                  <Box
                                    style={{
                                      width: 52,
                                      height: 5,
                                      borderRadius: 2,
                                      background: "var(--border)",
                                      position: "relative",
                                      flexShrink: 0,
                                    }}
                                  >
                                    <Box
                                      style={{
                                        position: "absolute",
                                        left: 0,
                                        top: 0,
                                        bottom: 0,
                                        width: `${barPct}%`,
                                        borderRadius: 2,
                                        background: "var(--primary)",
                                      }}
                                    />
                                  </Box>
                                  <Text
                                    span
                                    style={{
                                      fontFamily: "monospace",
                                      fontSize: "0.68rem",
                                      whiteSpace: "nowrap",
                                      overflow: "hidden",
                                      maxWidth: 110,
                                      textOverflow: "ellipsis",
                                    }}
                                    title={value}
                                  >
                                    {value.slice(0, 22)}
                                  </Text>
                                  <Text
                                    span
                                    c="dimmed"
                                    fz="0.65rem"
                                    ml="auto"
                                    style={{ flexShrink: 0 }}
                                  >
                                    ×{count}
                                  </Text>
                                </Group>
                              );
                            })}
                          </Box>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Box>
        );
      })()}
    </>
  );
}
