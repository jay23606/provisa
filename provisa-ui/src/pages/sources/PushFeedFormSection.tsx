// Copyright (c) 2026 Kenneth Stott
// Canary: 8b6e6f9c-4f0e-4c8d-9a3b-2c7d1e5f6a90
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1739: websocket/rss connection extras, extracted out of SourceFormFieldsExtended.tsx to
// keep that file under the eslint max-lines gate. Both fields' values ride in federation_hints
// (SourcesPage.tsx's federationHintsJson), never in a new SourceInput field — see push_wiring.py's
// websocket branch and subscribe.py's rss feed-url derivation for why host+port is already enough.

import { useTranslation } from "react-i18next";
import { Checkbox, NumberInput, TextInput } from "@mantine/core";
import { FormChecks, FormField } from "../../components/form/FormLayout";

interface PushFeedFormSectionProps {
  formType: string;
  wsUseSsl: boolean;
  setWsUseSsl: (v: boolean) => void;
  wsSubscribePayload: string;
  setWsSubscribePayload: (v: string) => void;
  wsEventPath: string;
  setWsEventPath: (v: string) => void;
  wsReconnectInterval: string;
  setWsReconnectInterval: (v: string) => void;
  rssFeedUrl: string;
  setRssFeedUrl: (v: string) => void;
  rssPollInterval: string;
  setRssPollInterval: (v: string) => void;
  rssUseSsl: boolean;
  setRssUseSsl: (v: boolean) => void;
}

export function PushFeedFormSection({
  formType,
  wsUseSsl,
  setWsUseSsl,
  wsSubscribePayload,
  setWsSubscribePayload,
  wsEventPath,
  setWsEventPath,
  wsReconnectInterval,
  setWsReconnectInterval,
  rssFeedUrl,
  setRssFeedUrl,
  rssPollInterval,
  setRssPollInterval,
  rssUseSsl,
  setRssUseSsl,
}: PushFeedFormSectionProps) {
  const { t } = useTranslation();
  return (
    <>
      {formType === "websocket" && (
        <>
          <FormChecks>
            <FormField size="short">
              <Checkbox
                label={t("sourceFormFieldsExtended.useSsl")}
                checked={wsUseSsl}
                onChange={(e) => setWsUseSsl(e.currentTarget.checked)}
                data-testid="websocket-use-ssl-checkbox"
              />
            </FormField>
          </FormChecks>
          <FormField size="long">
            <TextInput
              label={t("sourceFormFieldsExtended.eventPath")}
              value={wsEventPath}
              onChange={(e) => setWsEventPath(e.currentTarget.value)}
              placeholder="data.event"
              data-testid="websocket-event-path-input"
            />
          </FormField>
          <FormField size="short">
            <NumberInput
              label={t("sourceFormFieldsExtended.reconnectIntervalSeconds")}
              value={wsReconnectInterval === "" ? "" : Number(wsReconnectInterval)}
              onChange={(v) => setWsReconnectInterval(v === "" ? "" : String(v))}
              hideControls
              placeholder="5"
            />
          </FormField>
          <FormField size="long">
            <TextInput
              label={t("sourceFormFieldsExtended.subscribePayload")}
              value={wsSubscribePayload}
              onChange={(e) => setWsSubscribePayload(e.currentTarget.value)}
              placeholder='{"action":"subscribe","channel":"orders"}'
              data-testid="websocket-subscribe-payload-input"
            />
          </FormField>
        </>
      )}
      {formType === "rss" && (
        <>
          <FormField size="long">
            <TextInput
              label={t("sourceFormFieldsExtended.feedUrlOverride")}
              value={rssFeedUrl}
              onChange={(e) => setRssFeedUrl(e.currentTarget.value)}
              placeholder="https://example.com/feed.xml (overrides host/port/path)"
              data-testid="rss-feed-url-input"
            />
          </FormField>
          <FormField size="short">
            <NumberInput
              label={t("sourceFormFieldsExtended.pollIntervalSeconds")}
              value={rssPollInterval === "" ? "" : Number(rssPollInterval)}
              onChange={(v) => setRssPollInterval(v === "" ? "" : String(v))}
              hideControls
              placeholder="300"
            />
          </FormField>
          <FormChecks>
            <FormField size="short">
              <Checkbox
                label={t("sourceFormFieldsExtended.useSsl")}
                checked={rssUseSsl}
                onChange={(e) => setRssUseSsl(e.currentTarget.checked)}
                data-testid="rss-use-ssl-checkbox"
              />
            </FormField>
          </FormChecks>
        </>
      )}
    </>
  );
}
