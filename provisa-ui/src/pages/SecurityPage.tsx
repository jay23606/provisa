// Copyright (c) 2026 Kenneth Stott
// Canary: 09cc2288-9f68-4d9b-914e-1ba0f0e346d0
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import React, { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Trash2, Pencil } from "lucide-react";
import {
  Alert,
  Button,
  Group,
  ActionIcon,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { FilterInput } from "../components/admin/FilterInput";
import { HelpBubble } from "../components/HelpBubble";
import { MultiSelect } from "../components/MultiSelect";
import { useRoles, useDomains } from "../hooks/useAdminQueries";
import { useUpsertRole, useDeleteRole, useRevokeRoleGrants } from "../hooks/useSecurityQueries";
import { RoleGrantAction } from "../components/RoleGrantAction";
import { removeUserAssignment } from "../api/admin";
import type { Role, Capability } from "../types/auth";
import { useDomainFilter } from "../context/DomainFilterContext";
import { PageLoading } from "../components/PageLoading";
import { useDependentsDialog } from "../hooks/useDependentsDialog";
import { ResidencyGrant } from "../components/admin/ResidencyGrant";
import { CapabilityGrid, DomainsNote } from "./security/RoleFormParts";
import { useRegionChoices } from "../hooks/useRegionQueries";
import { ListTable, ListHead, ListRow, ListItems } from "../components/list/ListTable";
import { useListSortGroup, type ListColumn } from "../components/list/useListSortGroup";
import { PanelActions, SplitPane } from "../components/list/SplitPane";
import { serverMessage } from "../i18n/serverMessage";
import { FormField, FormFooter, FormIdentifiers, FormLayout } from "../components/form/FormLayout";

/** A role may be saved once it lists a domain — its own, or one a parent role hands down. */
function listsADomain(form: { domainAccess: string[]; parentRoleId: string }): boolean {
  return form.domainAccess.length > 0 || form.parentRoleId !== "";
}

const EMPTY_ROLE = {
  id: "",
  capabilities: [] as Capability[],
  domainAccess: [] as string[],
  parentRoleId: "" as string, // REQ-1677: "" = no parent
  residencyValues: [] as string[], // REQ-1921: with data_residency, the values it covers
  // REQ-1174: per-role rate + query-complexity limits ("" = unlimited on that dimension).
  reqPerSec: "" as number | "",
  maxComplexity: "" as number | "",
  maxTimeMs: "" as number | "",
};
export function SecurityRolesPage() {
  // REQ-1918: a delete is refused while anything depends on the object; this lists them, and
  // offers to take the role off each grant and assignment that can be removed in place.
  const { revokeFromTable, revokeFromObject } = useRevokeRoleGrants();
  const refusal = useDependentsDialog((roleId, dependent, all, handled) => (
    <RoleGrantAction
      roleId={roleId}
      dependent={dependent}
      all={all}
      handled={handled}
      revokeFromTable={revokeFromTable}
      revokeFromObject={revokeFromObject}
      removeAssignment={removeUserAssignment}
    />
  ));
  const { t } = useTranslation();
  const { setDomains: setContextDomains, setSelectedDomain } = useDomainFilter();
  const { roles, loading: rolesLoading, refetch: refetchRoles } = useRoles();
  const { domains, loading: domainsLoading, refetch: refetchDomains } = useDomains();
  const { upsertRole } = useUpsertRole();
  const regionChoices = useRegionChoices(); // REQ-1921: no regions, no data_residency
  const { deleteRole } = useDeleteRole();
  const loading = rolesLoading || domainsLoading;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [showRoleForm, setShowRoleForm] = useState(false);
  const [roleForm, setRoleForm] = useState(EMPTY_ROLE);
  const [expandedRole, setExpandedRole] = useState<string | null>(null);
  const [editingRoleInRow, setEditingRoleInRow] = useState<string | null>(null);
  const [roleSearch, setRoleSearch] = useState("");

  const reload = useCallback(async () => {
    await Promise.all([refetchRoles(), refetchDomains()]);
  }, [refetchRoles, refetchDomains]);

  useEffect(() => {
    setSelectedDomain("all");
  }, [setSelectedDomain]);

  useEffect(() => {
    setContextDomains(domains.map((x) => x.id));
  }, [domains, setContextDomains]);

  const handleNewRole = () => {
    setRoleForm({ ...EMPTY_ROLE });
    setShowRoleForm(true);
    setError("");
  };

  const handleSaveRole = async () => {
    if (!roleForm.id) return;
    setSaving(true);
    setError("");
    try {
      // REQ-1174: assemble the rate_limit input from the form; omit ("" → null) unset dimensions.
      const _n = (v: number | "") => (v === "" ? null : Number(v));
      const rateLimit = {
        requestsPerSecond: _n(roleForm.reqPerSec),
        maxQueryComplexity: _n(roleForm.maxComplexity),
        maxQueryTimeMs: _n(roleForm.maxTimeMs),
      };
      const hasLimit = Object.values(rateLimit).some((v) => v !== null);
      const res = await upsertRole({
        id: roleForm.id,
        capabilities: roleForm.capabilities,
        domainAccess: roleForm.domainAccess,
        rateLimit: hasLimit ? rateLimit : null,
        parentRoleId: roleForm.parentRoleId || null, // REQ-1677
        // REQ-1921: the grant's values go with the right; without it the role lists none.
        residencyValues: roleForm.capabilities.includes("data_residency")
          ? roleForm.residencyValues
          : [],
      });
      if (!res.success) {
        setError(serverMessage(res, res.message));
        return;
      }
      if (showRoleForm) {
        // The role exists now, with everything else at its defaults: it is selected in the list
        // and its detail opens in edit, where its capabilities and limits are set.
        setShowRoleForm(false);
        setExpandedRole(roleForm.id);
        setEditingRoleInRow(roleForm.id);
      } else {
        setRoleForm({ ...EMPTY_ROLE });
        setEditingRoleInRow(null);
      }
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRole = async (id: string) => {
    setSaving(true);
    setError("");
    try {
      const result = await deleteRole(id);
      if (refusal.refused(result, id)) return;
      if (!result.success) {
        setError(serverMessage(result, result.message));
        return;
      }
      if (expandedRole === id) setExpandedRole(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const startEditingRole = (role: Role) => {
    setRoleForm({
      id: role.id,
      capabilities: [...role.capabilities],
      domainAccess: [...role.domain_access],
      parentRoleId: role.parentRoleId ?? "", // REQ-1677
      residencyValues: [...(role.residencyValues ?? [])], // REQ-1921
      reqPerSec: role.rateLimit?.requestsPerSecond ?? "",
      maxComplexity: role.rateLimit?.maxQueryComplexity ?? "",
      maxTimeMs: role.rateLimit?.maxQueryTimeMs ?? "",
    });
    setEditingRoleInRow(role.id);
    setError("");
  };

  const toggleCapability = (cap: Capability) => {
    setRoleForm((f) => ({
      ...f,
      capabilities: f.capabilities.includes(cap)
        ? f.capabilities.filter((c) => c !== cap)
        : [...f.capabilities, cap],
    }));
  };

  const domainOptions = [
    { id: "*", label: t("securityPage.allDomains") },
    ...domains.map((d) => ({ id: d.id, label: d.id })),
  ];

  // REQ-1940: sort and group are the shared list mechanism.
  const filteredRoles = roles.filter(
    (r) => !roleSearch.trim() || r.id.toLowerCase().includes(roleSearch.toLowerCase()),
  );
  const roleColumns: ListColumn<Role>[] = [
    { key: "id", label: t("securityPage.colId"), sortValue: (r) => r.id },
    {
      key: "capabilities",
      label: t("securityPage.colCapabilities"),
      sortValue: (r) => r.capabilities.join(", "),
      groupValue: (r) => r.capabilities.join(", "),
    },
    {
      key: "domains",
      label: t("securityPage.colDomainAccess"),
      sortValue: (r) => r.domain_access.join(", "),
      groupValue: (r) => r.domain_access.join(", ") || t("securityPage.noDomains"),
    },
  ];
  const roleSortGroup = useListSortGroup(filteredRoles, roleColumns, "roles");

  if (loading) return <PageLoading message={t("securityPage.loadingRoles")} />;

  // The right-hand panel: the form that adds a role while it is open, otherwise the selected
  // role -- its detail, or the form that edits it. A role whose details are hidden from this user
  // has nothing to show, so it opens no panel.
  const closeRolePanel = () => {
    setShowRoleForm(false);
    setEditingRoleInRow(null);
    setExpandedRole(null);
  };
  const selectedRole =
    expandedRole === null
      ? null
      : (roles.find((x) => x.id === expandedRole && !x.detailsHidden) ?? null);
  const rolePanelTitle = showRoleForm
    ? t("securityPage.panelNewRole")
    : selectedRole
      ? selectedRole.id
      : "";
  // The first step of a new role asks only for what a role needs in order to exist: its id, and a
  // domain -- its own, or one a parent role hands down. It is a part of the form that edits a role.
  const rolePanelBody = showRoleForm ? (
    <FormLayout>
      <FormIdentifiers>
        <FormField size="medium">
          <TextInput
            label={t("securityPage.roleId")}
            placeholder={t("securityPage.roleIdPlaceholder")}
            value={roleForm.id}
            onChange={(e) => setRoleForm({ ...roleForm, id: e.target.value })}
            data-testid="role-id-input"
          />
        </FormField>
      </FormIdentifiers>
      <FormField size="long">
        <MultiSelect
          label={t("securityPage.domainAccess")}
          placeholder={t("securityPage.chooseDomains")}
          options={domainOptions}
          value={roleForm.domainAccess}
          onChange={(selected) => setRoleForm({ ...roleForm, domainAccess: selected })}
        />
      </FormField>
      {!listsADomain(roleForm) && (
        <FormField size="full">
          <DomainsNote savedWithNone={false} />
        </FormField>
      )}
      {/* REQ-1677: single parent; the chain is walked child-first at build time. */}
      <FormField help={t("securityPage.parentRoleHelp")} size="medium">
        <Select
          label={t("securityPage.parentRole")}
          placeholder={t("securityPage.parentRoleNone")}
          data={roles
            .filter((r) => r.id !== roleForm.id)
            .map((r) => ({ value: r.id, label: r.id }))}
          value={roleForm.parentRoleId || null}
          onChange={(v) => setRoleForm({ ...roleForm, parentRoleId: v ?? "" })}
          clearable
          searchable
          data-testid="role-parent-select"
        />
      </FormField>
      <FormFooter
        onSave={handleSaveRole}
        saving={saving}
        onCancel={() => setShowRoleForm(false)}
        saveProps={{ "data-testid": "save-role", disabled: !listsADomain(roleForm) }}
        cancelProps={{ "data-testid": "cancel-role" }}
      />
    </FormLayout>
  ) : selectedRole ? (
    ((r) => (
      <>
        {/* The role's actions sit in the panel's head, out of use while its form is open. */}
        <PanelActions>
          <fieldset className="panel-action-set" disabled={editingRoleInRow === r.id}>
            <Group gap="xs">
              <ActionIcon
                variant="subtle"
                aria-label={t("securityPage.edit")}
                data-testid={`edit-role-${r.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  startEditingRole(r);
                }}
              >
                <Pencil size={14} />
              </ActionIcon>
              <ConfirmDialog
                title={t("securityPage.deleteRoleTitle", { id: r.id })}
                consequence={t("securityPage.deleteRoleConsequence")}
                onConfirm={() => handleDeleteRole(r.id)}
              >
                {(open) => (
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={t("securityPage.delete")}
                    data-testid={`delete-role-${r.id}`}
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
        {editingRoleInRow !== r.id ? (
          <Stack gap="xs">
            <Text>
              <strong>{t("securityPage.labelId")}</strong> {r.id}
            </Text>
            <Text>
              <strong>{t("securityPage.labelCapabilities")}</strong>{" "}
              {r.capabilities.join(", ") || t("securityPage.none")}
            </Text>
            <Text>
              <strong>{t("securityPage.labelDomainAccess")}</strong>{" "}
              {r.domain_access.join(", ") || t("securityPage.noDomains")}
            </Text>
            <Text data-testid={`role-parent-${r.id}`}>
              <strong>{t("securityPage.labelParentRole")}</strong>{" "}
              {r.parentRoleId || t("securityPage.none")}
            </Text>
          </Stack>
        ) : (
          <FormLayout>
            <CapabilityGrid
              value={roleForm.capabilities}
              onToggle={toggleCapability}
              label={t("securityPage.capabilities")}
            />
            <ResidencyGrant
              held={roleForm.capabilities.includes("data_residency")}
              values={roleForm.residencyValues}
              regions={regionChoices.regions}
              onHeld={() => toggleCapability("data_residency")}
              onValues={(residencyValues) => setRoleForm({ ...roleForm, residencyValues })}
            />
            <FormField size="long">
              <MultiSelect
                label={t("securityPage.domainAccess")}
                placeholder={t("securityPage.chooseDomains")}
                options={domainOptions}
                value={roleForm.domainAccess}
                onChange={(selected) => setRoleForm({ ...roleForm, domainAccess: selected })}
              />
            </FormField>
            {!listsADomain(roleForm) && (
              <FormField size="full">
                <DomainsNote savedWithNone={r.domain_access.length === 0} />
              </FormField>
            )}
            <FormField size="medium">
              <Select
                label={t("securityPage.parentRole")}
                placeholder={t("securityPage.parentRoleNone")}
                data={roles.filter((x) => x.id !== r.id).map((x) => ({ value: x.id, label: x.id }))}
                value={roleForm.parentRoleId || null}
                onChange={(v) => setRoleForm({ ...roleForm, parentRoleId: v ?? "" })}
                clearable
                searchable
                data-testid={`role-parent-select-${r.id}`}
              />
            </FormField>
            {/* REQ-1174: per-role rate + query-complexity limits. Blank = unlimited on that dimension. */}
            <FormField size="full">
              <Text size="sm" fw={600}>
                {t("securityPage.limitsHeading", "Rate & query-complexity limits")}
              </Text>
            </FormField>
            <FormField size="short">
              <NumberInput
                label={t("securityPage.rateReqPerSec", "Requests / sec")}
                placeholder={t("securityPage.unlimited", "unlimited")}
                min={1}
                data-testid="role-req-per-sec"
                value={roleForm.reqPerSec}
                onChange={(v) =>
                  setRoleForm({ ...roleForm, reqPerSec: typeof v === "number" ? v : "" })
                }
              />
            </FormField>
            <FormField
              help={t(
                "securityPage.maxQueryComplexityHint",
                "Relations, joins, columns and nested queries of one statement, on every interface. The org limit still applies.",
              )}
              size="short"
            >
              <NumberInput
                label={t("securityPage.maxQueryComplexity", "Max query complexity")}
                placeholder={t("securityPage.unlimited", "unlimited")}
                min={1}
                data-testid="role-max-complexity"
                value={roleForm.maxComplexity}
                onChange={(v) =>
                  setRoleForm({ ...roleForm, maxComplexity: typeof v === "number" ? v : "" })
                }
              />
            </FormField>
            <FormField size="short">
              <NumberInput
                label={t("securityPage.maxQueryTimeMs", "Max query time (ms)")}
                placeholder={t("securityPage.unlimited", "unlimited")}
                min={1}
                data-testid="role-max-time-ms"
                value={roleForm.maxTimeMs}
                onChange={(v) =>
                  setRoleForm({ ...roleForm, maxTimeMs: typeof v === "number" ? v : "" })
                }
              />
            </FormField>
            <FormFooter
              onSave={handleSaveRole}
              saving={saving}
              onCancel={() => setEditingRoleInRow(null)}
              saveProps={{
                "data-testid": `save-role-${r.id}`,
                disabled: !listsADomain(roleForm),
              }}
            />
          </FormLayout>
        )}
      </>
    ))(selectedRole)
  ) : null;

  return (
    // The list and its panel share the height the heading leaves; each scrolls by itself.
    <Stack gap="md" p="md" className="page-sticky-head">
      {error && (
        <Alert color="red" data-testid="security-roles-error">
          {error}
        </Alert>
      )}

      <Group justify="space-between" wrap="wrap">
        <Title order={2}>{t("securityPage.rolesHeading")}</Title>
        <FilterInput
          value={roleSearch}
          onChange={setRoleSearch}
          placeholder={t("securityPage.filterByRoleId")}
        />
        {/* Nested Group: the parent spreads its children, and the bubble explains this
            button, so it has to travel with it. */}
        <Group gap="xs">
          {!showRoleForm && (
            <Button
              data-testid="toggle-role-form"
              onClick={() => {
                setExpandedRole(null);
                handleNewRole();
              }}
            >
              {t("securityPage.addRole")}
            </Button>
          )}
          <HelpBubble
            title={t("securityPage.rolePurposeTitle")}
            paragraphs={[t("securityPage.rolePurposeBody"), t("securityPage.rolePurposeAdd")]}
            ariaLabel={t("securityPage.rolePurposeAria")}
            testId="roles-purpose-help"
          />
        </Group>
      </Group>

      <SplitPane
        testId="roles-split"
        storageKey="provisa.roles.detailWidth"
        title={rolePanelTitle}
        onClose={closeRolePanel}
        // Escape closes a role that is only being looked at; it never drops what is being typed.
        closeOnEscape={!showRoleForm && editingRoleInRow === null}
        labels={{
          panel: t("securityPage.roleDetailPanel"),
          resize: t("tablesPage.resizeDetail"),
          expand: t("tablesPage.expandDetail"),
          restore: t("tablesPage.restoreDetail"),
          close: t("tablesPage.closeDetail"),
          backToList: t("tablesPage.backToList"),
        }}
        list={
          <ListTable minWidth={480} testId="roles-list">
            <ListHead
              sortGroup={roleSortGroup}
              columns={[{ col: "id" }, { col: "capabilities" }, { col: "domains" }]}
            />
            <Table.Tbody>
              <ListItems
                state={roleSortGroup}
                colSpan={3}
                rowKey={(r) => r.id}
                render={(r) => (
                  <React.Fragment>
                    <ListRow
                      // The row whose detail the right-hand panel is showing.
                      selected={selectedRole?.id === r.id}
                      onClick={() => {
                        // The row opens its detail in the panel, swaps it, or closes it.
                        setExpandedRole(expandedRole === r.id ? null : r.id);
                        setEditingRoleInRow(null);
                        setShowRoleForm(false);
                      }}
                    >
                      <Table.Td>{r.id}</Table.Td>
                      {r.detailsHidden ? (
                        <Table.Td
                          colSpan={2}
                          c="dimmed"
                          data-testid={`role-details-hidden-${r.id}`}
                        >
                          {t("securityPage.detailsHidden")}
                        </Table.Td>
                      ) : (
                        <>
                          <Table.Td>{r.capabilities.join(", ")}</Table.Td>
                          <Table.Td data-testid={`role-domains-${r.id}`}>
                            {r.domain_access.join(", ") || t("securityPage.noDomains")}
                          </Table.Td>
                        </>
                      )}
                    </ListRow>
                  </React.Fragment>
                )}
              />
            </Table.Tbody>
          </ListTable>
        }
      >
        {rolePanelBody}
      </SplitPane>
      {refusal.dialog}
    </Stack>
  );
}

export { SecurityRolesPage as SecurityPage };
