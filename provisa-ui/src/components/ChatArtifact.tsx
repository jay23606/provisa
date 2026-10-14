// Copyright (c) 2026 Kenneth Stott
// Canary: 7c3e1a95-4b26-4d80-9f71-5e2b8d6a0c14
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { Box, Button, Group, Image, Text } from "@mantine/core";
import { Download, Network } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toResultRedirect } from "../api/admin";
import type { ChatArtifact as Artifact } from "../hooks/useMcpChat";
import { ResultRedirectNotice } from "./ResultRedirectNotice";

/**
 * What Polly handed over in a reply, besides its text: a graph it drew, with a download of the
 * picture and a way to run the same statement on the Graph page; or a result delivered as a file,
 * with its download.
 */
export function ChatArtifact({ artifact }: { artifact: Artifact }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  if (artifact.kind === "file") {
    return (
      <Box mt="xs">
        <ResultRedirectNotice redirect={toResultRedirect(artifact)} />
      </Box>
    );
  }
  const src = `data:image/png;base64,${artifact.png}`;
  const caption = t("chatPanel.graphCaption", {
    nodes: artifact.nodes,
    relationships: artifact.relationships,
  });
  return (
    <Box data-testid="chat-graph" mt="xs">
      <Image src={src} alt={caption} radius="sm" bd="1px solid var(--mantine-color-default-border)" />
      <Text size="xs" c="dimmed" mt={4}>
        {caption}
      </Text>
      <Group gap="xs" mt={4}>
        <Button
          component="a"
          href={src}
          download="graph.png"
          size="compact-xs"
          variant="light"
          leftSection={<Download size={12} />}
          data-testid="chat-graph-download"
        >
          {t("chatPanel.downloadPng")}
        </Button>
        <Button
          size="compact-xs"
          variant="light"
          leftSection={<Network size={12} />}
          onClick={() => navigate("/graph", { state: { query: artifact.cypher, autoRun: true } })}
          data-testid="chat-graph-open"
        >
          {t("chatPanel.openOnGraphPage")}
        </Button>
      </Group>
    </Box>
  );
}
