// Copyright (c) 2026 Kenneth Stott
// Canary: fb81a4a2-6ded-49c4-bf70-fef30f50f05c
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import type { ReactElement } from "react";
import { ActionIcon, Stack, Text } from "@mantine/core";
import { CircleHelp } from "lucide-react";
import { TipSurface } from "./Tip";

/**
 * The explanation attached to a page control. It answers what the control is FOR — what
 * the object does once it exists, or what the tool behind an icon actually opens — because
 * the label already says what it does and the purpose is the part nobody can read off the
 * screen.
 *
 * Beside an add button it renders its own "?" target. An icon-only button is already the
 * opaque thing being explained, so it passes itself as `target` and hovering the icon opens
 * the card: a second "?" per icon would double the row of glyphs it is meant to decode.
 */
export function HelpBubble({
  title,
  paragraphs,
  ariaLabel,
  testId,
  target,
}: {
  title: string;
  paragraphs: string[];
  ariaLabel: string;
  testId: string;
  target?: ReactElement;
}) {
  return (
    // The same surface as every one-line hint (components/Tip.tsx), as a titled card.
    <TipSurface
      card
      position="bottom-end"
      testId={`${testId}-card`}
      content={
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            {title}
          </Text>
          {paragraphs.map((p) => (
            <Text key={p} size="xs" c="dimmed">
              {p}
            </Text>
          ))}
        </Stack>
      }
    >
      {target ?? (
        <ActionIcon variant="subtle" color="gray" aria-label={ariaLabel} data-testid={testId}>
          <CircleHelp size={16} />
        </ActionIcon>
      )}
    </TipSurface>
  );
}
