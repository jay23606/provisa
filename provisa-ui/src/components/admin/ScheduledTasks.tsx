// Copyright (c) 2026 Kenneth Stott
// Canary: ce243a88-d4cf-41a3-99e0-741e6acd3802
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Badge,
  Button,
  Card,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { Plus } from "lucide-react";
import {
  useScheduledTasks,
  useToggleScheduledTask,
  useCreateScheduledTask,
  useDeleteScheduledTask,
} from "../../hooks/useAdminOpsQueries";
import { useRoles } from "../../hooks/useAdminQueries";
import { fetchActions, type TrackedWebhook } from "../../api/actions";
import { ListRow } from "../list/ListTable";
import { SortGroupTable } from "../list/SortGroupTable";
import { FormField, FormFooter, FormIdentifiers, FormLayout } from "../form/FormLayout";

const PAGE_SIZE = 50;

type TriggerKind = "webhook" | "sql";

export function ScheduledTasks() {
  const { t } = useTranslation();
  const { scheduledTasks: tasks, loading } = useScheduledTasks();
  const { toggleScheduledTask } = useToggleScheduledTask();
  const { createScheduledTask } = useCreateScheduledTask();
  const { deleteScheduledTask } = useDeleteScheduledTask();
  const [toggling, setToggling] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [taskPage, setTaskPage] = useState(1);
  const [grouped, setGrouped] = useState(false);

  const [webhooks, setWebhooks] = useState<TrackedWebhook[]>([]);
  useEffect(() => {
    fetchActions()
      .then((a) => setWebhooks(a.webhooks))
      .catch(() => {});
  }, []);

  const [showForm, setShowForm] = useState(false);
  const [newKind, setNewKind] = useState<TriggerKind>("webhook");
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newCron, setNewCron] = useState("");
  const [newWebhookName, setNewWebhookName] = useState("");
  const [newSql, setNewSql] = useState("");
  // The role a SQL task's statement runs as, through the write admission; required.
  const [newRole, setNewRole] = useState<string | null>(null);
  const { roles } = useRoles();
  const [argValues, setArgValues] = useState<Record<string, string>>({});
  const [formMsg, setFormMsg] = useState("");
  const [creating, setCreating] = useState(false);

  const selectedWebhook = webhooks.find((w) => w.name === newWebhookName) ?? null;

  const resetForm = () => {
    setNewId("");
    setNewName("");
    setNewCron("");
    setNewWebhookName("");
    setNewSql("");
    setNewRole(null);
    setArgValues({});
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    setToggling(id);
    await toggleScheduledTask(id, enabled);
    setToggling(null);
  };

  const handleDelete = async (id: string) => {
    setDeleting(id);
    await deleteScheduledTask(id);
    setDeleting(null);
  };

  const handleCreate = async () => {
    if (!newId.trim() || !newName.trim() || !newCron.trim()) {
      setFormMsg(t("scheduledTasks.validationRequired"));
      return;
    }
    if (newKind === "webhook" && !newWebhookName) {
      setFormMsg(t("scheduledTasks.validationWebhookRequired"));
      return;
    }
    if (newKind === "sql" && !newSql.trim()) {
      setFormMsg(t("scheduledTasks.validationSqlRequired"));
      return;
    }
    if (newKind === "sql" && !newRole) {
      setFormMsg(t("scheduledTasks.validationRoleRequired"));
      return;
    }
    setCreating(true);
    setFormMsg("");
    const result = await createScheduledTask(
      newKind === "webhook"
        ? {
            id: newId.trim(),
            name: newName.trim(),
            cron: newCron.trim(),
            kind: "webhook",
            webhookName: newWebhookName,
            argsJson: Object.keys(argValues).length ? JSON.stringify(argValues) : undefined,
          }
        : {
            id: newId.trim(),
            name: newName.trim(),
            cron: newCron.trim(),
            kind: "sql",
            sql: newSql.trim(),
            role: newRole ?? undefined,
          },
    );
    setCreating(false);
    if (result.success) {
      setShowForm(false);
      resetForm();
    } else {
      setFormMsg(result.message);
    }
  };

  if (loading) return <Text>{t("scheduledTasks.loading")}</Text>;

  const totalPages = Math.max(1, Math.ceil(tasks.length / PAGE_SIZE));

  return (
    <Stack gap="md">
      {!showForm && (
        <FormFooter>
          <Button
            data-testid="scheduled-tasks-toggle-form"
            onClick={() => {
              setShowForm(true);
              setFormMsg("");
            }}
            leftSection={<Plus size={14} />}
          >
            {t("scheduledTasks.addButton")}
          </Button>
        </FormFooter>
      )}

      {showForm && (
        <Card withBorder padding="md">
          <FormLayout>
            <FormIdentifiers>
              <FormField size="medium">
                <TextInput
                  label={t("scheduledTasks.idLabel")}
                  value={newId}
                  onChange={(e) => setNewId(e.currentTarget.value)}
                  placeholder={t("scheduledTasks.idPlaceholder")}
                />
              </FormField>
              <FormField size="medium">
                <TextInput
                  label={t("scheduledTasks.nameLabel")}
                  value={newName}
                  onChange={(e) => setNewName(e.currentTarget.value)}
                  placeholder={t("scheduledTasks.namePlaceholder")}
                />
              </FormField>
            </FormIdentifiers>
            <FormField size="medium">
              <Select
                label={t("scheduledTasks.kindLabel")}
                aria-label={t("scheduledTasks.kindLabel")}
                data={[
                  { value: "webhook", label: t("scheduledTasks.kindWebhook") },
                  { value: "sql", label: t("scheduledTasks.kindSql") },
                ]}
                value={newKind}
                onChange={(v) => {
                  setNewKind((v as TriggerKind) ?? "webhook");
                  setFormMsg("");
                }}
                allowDeselect={false}
              />
            </FormField>
            <FormField size="medium">
              <TextInput
                label={t("scheduledTasks.cronLabel")}
                value={newCron}
                onChange={(e) => setNewCron(e.currentTarget.value)}
                placeholder={t("scheduledTasks.cronPlaceholder")}
              />
            </FormField>

            {newKind === "webhook" ? (
              <>
                <FormField size="medium">
                  <Select
                    label={t("scheduledTasks.webhookLabel")}
                    placeholder={t("scheduledTasks.webhookPlaceholder")}
                    data={webhooks.map((w) => ({ value: w.name, label: w.name }))}
                    value={newWebhookName || null}
                    onChange={(v) => {
                      setNewWebhookName(v ?? "");
                      setArgValues({});
                    }}
                  />
                </FormField>
                {selectedWebhook?.arguments.map((arg) => (
                  <FormField size="medium" key={arg.name}>
                    <TextInput
                      label={
                        <>
                          {arg.name}{" "}
                          <Text span c="dimmed" fz="xs">
                            ({arg.type})
                          </Text>
                        </>
                      }
                      value={argValues[arg.name] ?? ""}
                      onChange={(e) => {
                        const next = e.currentTarget.value;
                        setArgValues((prev) => ({ ...prev, [arg.name]: next }));
                      }}
                      placeholder={arg.type}
                    />
                  </FormField>
                ))}
              </>
            ) : (
              <>
                <FormField size="full" hint={t("scheduledTasks.sqlTokensHint")}>
                  <Textarea
                    label={t("scheduledTasks.sqlLabel")}
                    aria-label={t("scheduledTasks.sqlLabel")}
                    value={newSql}
                    onChange={(e) => setNewSql(e.currentTarget.value)}
                    placeholder={t("scheduledTasks.sqlPlaceholder")}
                    rows={4}
                    styles={{ input: { fontFamily: "monospace" } }}
                  />
                </FormField>
                <FormField size="medium">
                  <Select
                    label={t("scheduledTasks.roleLabel")}
                    aria-label={t("scheduledTasks.roleLabel")}
                    data={roles.map((r) => r.id)}
                    value={newRole}
                    onChange={setNewRole}
                    data-testid="scheduled-task-role"
                  />
                </FormField>
              </>
            )}

            {formMsg && (
              <FormField size="full">
                <Text c="red" fz="sm">
                  {formMsg}
                </Text>
              </FormField>
            )}
            <FormFooter
              onSave={handleCreate}
              saving={creating}
              onCancel={() => {
                setShowForm(false);
                setFormMsg("");
              }}
              saveProps={{ "data-testid": "scheduled-tasks-submit" }}
            />
          </FormLayout>
        </Card>
      )}

      {tasks.length === 0 ? (
        <Text c="dimmed">{t("scheduledTasks.empty")}</Text>
      ) : (
        <>
          <SortGroupTable
            testPrefix="scheduled-tasks"
            minWidth={800}
            rows={tasks}
            columns={[
              { key: "id", label: t("scheduledTasks.colId"), sortValue: (k) => k.id },
              { key: "name", label: t("scheduledTasks.colName"), sortValue: (k) => k.name },
              {
                key: "cron",
                label: t("scheduledTasks.colCron"),
                sortValue: (k) => k.cronExpression,
              },
              {
                key: "kind",
                label: t("scheduledTasks.colKind"),
                sortValue: (k) => k.kind,
                groupValue: (k) => k.kind,
              },
              {
                key: "enabled",
                label: t("scheduledTasks.colEnabled"),
                sortValue: (k) => (k.enabled ? 1 : 0),
                groupValue: (k) => String(k.enabled),
              },
              {
                key: "lastRun",
                label: t("scheduledTasks.colLastRun"),
                sortValue: (k) => k.lastRunAt ?? "",
              },
              {
                key: "nextRun",
                label: t("scheduledTasks.colNextRun"),
                sortValue: (k) => k.nextRunAt ?? "",
              },
            ]}
            headers={[
              { col: "id" },
              { col: "name" },
              { col: "cron" },
              { col: "kind" },
              t("scheduledTasks.colTarget"),
              { col: "enabled" },
              { col: "lastRun" },
              { col: "nextRun" },
              t("scheduledTasks.colActions"),
            ]}
            colSpan={9}
            rowKey={(task) => task.id}
            page={{ index: taskPage - 1, size: PAGE_SIZE }}
            onGroupedChange={setGrouped}
            render={(task) => (
              <ListRow key={task.id}>
                <Table.Td>
                  <Text ff="monospace" fz="sm">
                    {task.id}
                  </Text>
                </Table.Td>
                <Table.Td>{task.name}</Table.Td>
                <Table.Td>
                  <Text ff="monospace" fz="sm">
                    {task.cronExpression}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light">{task.kind}</Badge>
                </Table.Td>
                <Table.Td maw={300}>
                  {task.kind === "sql" ? (
                    <Stack gap={2}>
                      <Text ff="monospace" fz="sm">
                        {task.sql}
                      </Text>
                      <Text c="dimmed" fz="xs">
                        {t("scheduledTasks.runsAs", { role: task.role })}
                      </Text>
                    </Stack>
                  ) : (
                    task.webhookUrl || t("scheduledTasks.noTarget")
                  )}
                </Table.Td>
                <Table.Td>
                  <Badge color={task.enabled ? "green" : "gray"} variant="light">
                    {task.enabled ? t("scheduledTasks.enabled") : t("scheduledTasks.disabled")}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {task.lastRunAt
                    ? new Date(task.lastRunAt).toLocaleString()
                    : t("scheduledTasks.never")}
                </Table.Td>
                <Table.Td>
                  {task.nextRunAt
                    ? new Date(task.nextRunAt).toLocaleString()
                    : t("scheduledTasks.noNextRun")}
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Button
                      size="compact-xs"
                      onClick={() => handleToggle(task.id, !task.enabled)}
                      disabled={toggling === task.id}
                    >
                      {toggling === task.id
                        ? t("scheduledTasks.working")
                        : task.enabled
                          ? t("scheduledTasks.disable")
                          : t("scheduledTasks.enable")}
                    </Button>
                    <Button
                      size="compact-xs"
                      color="red"
                      variant="light"
                      onClick={() => handleDelete(task.id)}
                      disabled={deleting === task.id}
                    >
                      {deleting === task.id
                        ? t("scheduledTasks.working")
                        : t("scheduledTasks.delete")}
                    </Button>
                  </Group>
                </Table.Td>
              </ListRow>
            )}
          />
          {totalPages > 1 && !grouped && (
            <Group justify="flex-end">
              <Pagination total={totalPages} value={taskPage} onChange={setTaskPage} size="sm" />
            </Group>
          )}
        </>
      )}
    </Stack>
  );
}
