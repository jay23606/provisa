// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2006: /demos/<name>, the live demos page's "Open live demo". It opens a visitor's sandbox of
// the demo -- no sign-in -- and goes to it; a refusal (an unknown demo, every sandbox in use, a
// demo still being prepared) is shown as the server words it, with a way to try again.

import { Alert, Button, Center, Loader, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { openDemoSandbox, SandboxRefused, type OpenedSandbox } from "../../api/demoSandbox";
import { orgOrigin } from "../../lib/authHost";
import { sandboxDestination } from "../../lib/sandboxSession";

/** Refusals that pass with time: the page offers to try again. */
const TRANSIENT = new Set(["sandbox.at_capacity", "sandbox.demo_not_ready"]);

function go(opened: OpenedSandbox): void {
  window.location.assign(sandboxDestination(opened.org_id, opened.token, orgOrigin(opened.org_id)));
}

function asRefusal(e: unknown): SandboxRefused {
  return e instanceof SandboxRefused ? e : new SandboxRefused(String(e), null);
}

export function DemoOpenPage() {
  const { t } = useTranslation();
  const { name = "" } = useParams<{ name: string }>();
  const [refusal, setRefusal] = useState<SandboxRefused | null>(null);

  useEffect(() => {
    let current = true;
    openDemoSandbox(name)
      .then(go)
      .catch((e: unknown) => {
        if (current) setRefusal(asRefusal(e));
      });
    return () => {
      current = false;
    };
  }, [name]);

  const retry = () => {
    setRefusal(null);
    openDemoSandbox(name)
      .then(go)
      .catch((e: unknown) => setRefusal(asRefusal(e)));
  };

  return (
    <Center mih="60vh" p="md">
      <Stack align="center" gap="md" maw={520}>
        <Title order={2}>{t("demoOpenPage.title")}</Title>
        {refusal === null ? (
          <>
            <Loader data-testid="demo-open-loading" />
            <Text c="dimmed" ta="center">
              {t("demoOpenPage.opening")}
            </Text>
          </>
        ) : (
          <>
            <Alert color={TRANSIENT.has(refusal.code ?? "") ? "yellow" : "red"} data-testid="demo-open-refused">
              {refusal.message}
            </Alert>
            {TRANSIENT.has(refusal.code ?? "") && (
              <Button onClick={retry} data-testid="demo-open-retry">
                {t("demoOpenPage.retry")}
              </Button>
            )}
          </>
        )}
      </Stack>
    </Center>
  );
}

export default DemoOpenPage;
