// Copyright (c) 2026 Kenneth Stott
// Canary: 3b8f5e20-6c1d-4a97-8e43-f2d9a7c05b18
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The source form's "Load Management and Recency Controls" panel: every operator setting that
// governs how hard Provisa leans on this source and how fresh its data is — caching, the change
// signal, replication and load protection (REQ-826/1141), grouped and collapsed by default.

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox, NumberInput, Select, Text, TextInput } from "@mantine/core";
import { SOURCE_PROBE_SOURCE_TYPES, sourceChangeSignals } from "../../liveCapability";
import { CHANGE_SIGNAL_LABELS } from "./constants";
import { CollapsibleSection } from "../tables/CollapsibleSection";
import { ReplicateSelect } from "../../components/admin/ReplicateSelect";
import type { SourceFormFieldsProps } from "./SourceFormFields";
import {
  maxLiveConcurrencyValid,
  sentinelPathValid,
  sourceFormCacheTtl,
  sourceFormLanded,
  ttlSignalMissingCacheTtl,
} from "./loadManagement";
import { useSourceKind } from "./sourceKind";
import { FormChecks, FormField, FormLayout } from "../../components/form/FormLayout";

export function SourceLoadManagementPanel({
  form,
  setForm,
}: Pick<SourceFormFieldsProps, "form" | "setForm">) {
  const { t } = useTranslation();
  const kind = useSourceKind(form.type);
  const kindLands = kind?.cache_ttl_required === true;
  // Offered unless the server says a source of this kind can have no sentinel (REQ-1148).
  const sentinelApplies = kind?.sentinel_path !== false;
  const staleSentinel = !sentinelApplies && form.sentinelPath !== "";
  useEffect(() => {
    // A value typed for another kind is not carried into one that cannot have it.
    if (staleSentinel) setForm({ ...form, sentinelPath: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the value turns stale
  }, [staleSentinel]);
  return (
    <FormField size="full">
      <CollapsibleSection
        // Opened when the kind needs a Cache TTL, so the field that must be filled is in view.
        key={kindLands ? "cache-ttl-required" : "optional"}
        defaultOpen={kindLands}
        title={t("sourceFormFieldsExtended.loadManagementTitle")}
        testId="source-load-management-panel"
        info={{
          label: t("sourceFormFieldsExtended.loadManagementInfoLabel"),
          text: t("sourceFormFieldsExtended.loadManagementInfo"),
        }}
      >
        {/* The operator's load and recency controls for this source, grouped: caching, the
            change signal, replication and load protection (REQ-826/1141). */}
        <Text size="xs" c="dimmed" data-testid="source-load-management-help">
          {t("sourceFormFieldsExtended.loadManagementHelp")}
        </Text>
        <FormLayout>
          <FormField size="medium">
            <ReplicateSelect
              value={form.replicate}
              onChange={(replicate) => setForm({ ...form, replicate })}
              scope="source"
              loadProtected={form.loadProtected}
              testId="source-replicate-select"
            />
          </FormField>
          {/* Medium, not short: its error is a sentence. */}
          <FormField size="medium">
            <NumberInput
              label={t("sourceFormFieldsExtended.cacheTtlSeconds")}
              min={0}
              value={form.cacheTtl === "" ? "" : Number(form.cacheTtl)}
              onChange={(v) => setForm({ ...form, cacheTtl: v === "" ? "" : String(v) })}
              placeholder={t("sourceFormFieldsExtended.cacheTtlPlaceholder")}
              required={kindLands}
              error={
                ttlSignalMissingCacheTtl(
                  form.changeSignal,
                  sourceFormCacheTtl(form.cacheTtl),
                  sourceFormLanded(form, kindLands),
                )
                  ? t("sourceFormFieldsExtended.cacheTtlRequiredForSignal", {
                      signal: form.changeSignal,
                    })
                  : undefined
              }
              data-testid="cache-ttl-input"
            />
          </FormField>
          <FormField help={t("sourceFormFieldsExtended.changeSignalTooltip")} size="medium">
            <Select
              label={t("sourceFormFieldsExtended.changeSignal")}
              value={form.changeSignal}
              onChange={(v) => setForm({ ...form, changeSignal: v ?? "" })}
              data={sourceChangeSignals(form.type).map((cs) => ({
                value: cs,
                // A source that asks its provider whether it changed says the choice in words.
                label: SOURCE_PROBE_SOURCE_TYPES.has(form.type)
                  ? t(`sourceFormFieldsExtended.sourceProbeSignal.${cs}`)
                  : (CHANGE_SIGNAL_LABELS[cs] ?? cs),
              }))}
              allowDeselect={false}
              data-testid="change-signal-select"
            />
          </FormField>
          {sentinelApplies && (
            <FormField help={t("sourceFormFieldsExtended.sentinelPathTooltip")} size="long">
              <TextInput
                label={t("sourceFormFieldsExtended.sentinelPath")}
                value={form.sentinelPath}
                onChange={(e) => setForm({ ...form, sentinelPath: e.currentTarget.value })}
                placeholder="https://example.com/data/_SUCCESS"
                error={
                  sentinelPathValid(form.sentinelPath)
                    ? undefined
                    : t("sourceFormFieldsExtended.sentinelPathInvalid")
                }
                data-testid="sentinel-path-input"
              />
            </FormField>
          )}
          <FormField help={t("sourceFormFieldsExtended.maxLiveConcurrencyHelp")} size="short">
            <NumberInput
              label={t("sourceFormFieldsExtended.maxLiveConcurrency")}
              min={1}
              allowDecimal={false}
              allowNegative={false}
              value={form.maxLiveConcurrency === "" ? "" : Number(form.maxLiveConcurrency)}
              onChange={(v) => setForm({ ...form, maxLiveConcurrency: v === "" ? "" : String(v) })}
              placeholder={t("sourceFormFieldsExtended.maxLiveConcurrencyPlaceholder")}
              error={
                maxLiveConcurrencyValid(form.maxLiveConcurrency)
                  ? undefined
                  : t("sourceFormFieldsExtended.maxLiveConcurrencyInvalid")
              }
              data-testid="max-live-concurrency-input"
            />
          </FormField>
          {/* REQ-1141: the off-peak window of a load-protected source. */}
          {form.loadProtected && (
            <>
              <FormField size="short">
                <TextInput
                  label={t("sourceFormFieldsExtended.offPeakWindow")}
                  value={form.offPeakWindow}
                  onChange={(e) => setForm({ ...form, offPeakWindow: e.currentTarget.value })}
                  placeholder="01:00-05:00"
                  data-testid="off-peak-window-input"
                />
              </FormField>
              <FormField size="short">
                <TextInput
                  label={t("sourceFormFieldsExtended.offPeakTz")}
                  value={form.offPeakTz}
                  onChange={(e) => setForm({ ...form, offPeakTz: e.currentTarget.value })}
                  placeholder="UTC"
                  data-testid="off-peak-tz-input"
                />
              </FormField>
            </>
          )}
          {/* The ticks sit together beneath the fields: caching, the freshness gate, load protection. */}
          <FormChecks>
            <FormField size="short" help={t("sourceFormFieldsExtended.cacheEnabledHelp")}>
              <Checkbox
                label={t("sourceFormFieldsExtended.cacheEnabled")}
                checked={form.cacheEnabled}
                onChange={(e) => setForm({ ...form, cacheEnabled: e.currentTarget.checked })}
                data-testid="cache-enabled-checkbox"
              />
            </FormField>
            <FormField help={t("sourceFormFieldsExtended.freshnessGateTooltip")} size="short">
              <Checkbox
                label={t("sourceFormFieldsExtended.freshnessGate")}
                checked={form.freshnessGate}
                onChange={(e) => setForm({ ...form, freshnessGate: e.currentTarget.checked })}
                data-testid="freshness-gate-checkbox"
              />
            </FormField>
            <FormField help={t("sourceFormFieldsExtended.loadProtectedTooltip")} size="short">
              <Checkbox
                label={t("sourceFormFieldsExtended.loadProtected")}
                checked={form.loadProtected}
                onChange={(e) => setForm({ ...form, loadProtected: e.currentTarget.checked })}
                data-testid="load-protected-checkbox"
              />
            </FormField>
          </FormChecks>
        </FormLayout>
      </CollapsibleSection>
    </FormField>
  );
}
