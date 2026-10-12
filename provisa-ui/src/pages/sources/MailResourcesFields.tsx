// Copyright (c) 2026 Kenneth Stott
// Canary: 9e4a1c63-7d2b-4b08-b5f3-2c6e8a0d1f47
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1994: what a Google Workspace or Microsoft 365 source reads, and its calendar settings:
// whether a change to an event tells its attendees, and (Microsoft 365) how many days either side
// of today a check for changes looks at.

import { Checkbox, NumberInput } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormChecks, FormField } from "../../components/form/FormLayout";
import { CALENDAR, MAIL, RESOURCES, TASKS, resourcesField, resourcesOf } from "./mailResources";

interface Props {
  /** The fields' prefix (`gw`, `m365`). */
  prefix: string;
  /** The test ids' prefix (`google-workspace`, `microsoft-365`). */
  testPrefix: string;
  fields: Record<string, string>;
  /** Sets fields that change what the provider is asked to grant: the approval is asked again. */
  setAsked: (changed: Record<string, string>) => void;
  /** Sets fields that change no grant. */
  set: (changed: Record<string, string>) => void;
  /** Whether the source states how many days a check for changes looks at (Microsoft 365). */
  checkDays: boolean;
}

const LABEL: Record<string, string> = {
  [MAIL]: "mailResources.mail",
  [CALENDAR]: "mailResources.calendar",
  [TASKS]: "mailResources.tasks",
};

export function MailResourcesFields({
  prefix,
  testPrefix,
  fields,
  setAsked,
  set,
  checkDays,
}: Props) {
  const { t } = useTranslation();
  const resources = resourcesOf(fields, prefix);
  const tick = (resource: string, on: boolean) => {
    const next = on ? [...resources, resource] : resources.filter((r) => r !== resource);
    // The days a check looks at start at a quarter of a year either side, until set.
    const days =
      checkDays && on && resource === CALENDAR && !fields[`${prefix}_check_days`]
        ? { [`${prefix}_check_days`]: "90" }
        : {};
    setAsked({ ...resourcesField(prefix, next), ...days });
  };
  return (
    <>
      <FormChecks>
        {RESOURCES.map((resource) => (
          <FormField key={resource} size="short">
            <Checkbox
              label={t(LABEL[resource])}
              checked={resources.includes(resource)}
              onChange={(e) => tick(resource, e.currentTarget.checked)}
              data-testid={`${testPrefix}-resource-${resource}`}
            />
          </FormField>
        ))}
      </FormChecks>
      {resources.includes(CALENDAR) && (
        <>
          <FormChecks>
            <FormField help={t("mailResources.sendUpdatesHelp")} size="long">
              <Checkbox
                label={t("mailResources.sendUpdates")}
                checked={fields[`${prefix}_send_updates`] === "true"}
                onChange={(e) =>
                  set({ [`${prefix}_send_updates`]: e.currentTarget.checked ? "true" : "" })
                }
                data-testid={`${testPrefix}-send-updates`}
              />
            </FormField>
          </FormChecks>
          {checkDays && (
            <FormField help={t("mailResources.checkDaysHelp")} size="short">
              <NumberInput
                label={t("mailResources.checkDays")}
                min={1}
                required
                value={fields[`${prefix}_check_days`] ? Number(fields[`${prefix}_check_days`]) : ""}
                onChange={(v) => set({ [`${prefix}_check_days`]: v === "" ? "" : String(v) })}
                data-testid={`${testPrefix}-check-days`}
              />
            </FormField>
          )}
        </>
      )}
    </>
  );
}
