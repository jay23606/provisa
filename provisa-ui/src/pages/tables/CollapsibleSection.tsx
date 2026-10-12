// Copyright (c) 2026 Kenneth Stott
// Canary: 6f2b9d14-7c38-4a56-9e01-3d5c8f4b7a29
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A per-MV config panel that collapses to reduce clutter. Children stay mounted (Mantine Collapse),
// so form state and testability are unaffected — the header only toggles visibility.

import { useState, type ReactNode } from "react";
import { ActionIcon, Badge, Collapse, Group, Text } from "@mantine/core";
import { Tip } from "../../components/Tip";
import { CircleHelp } from "lucide-react";
import { FormLayout } from "../../components/form/FormLayout";
import { useFormRead } from "../../components/form/formRead";

export function CollapsibleSection({
  title,
  testId,
  tourId,
  badge,
  info,
  defaultOpen = false,
  flat = false,
  children,
}: {
  title: string;
  testId: string;
  /** REQ-1358: `data-tour` on the section wrapper, so a tour step can highlight the whole panel. */
  tourId?: string;
  badge?: ReactNode;
  /** Explanatory text behind an (i) icon in the header, shown on hover or keyboard focus. */
  info?: { label: string; text: string };
  defaultOpen?: boolean;
  /** Always open, with no toggle: a section that is a whole tab's content, or most of it. */
  flat?: boolean;
  children: ReactNode;
}) {
  const [toggled, setOpen] = useState(defaultOpen);
  const open = flat || toggled;
  // In a form read the section is open, its title heading its fields.
  if (useFormRead()) {
    return (
      <>
        <div role="heading" aria-level={4} className="form-read__heading" data-testid={testId}>
          {title}
        </div>
        {children}
      </>
    );
  }
  return (
    <div className="form-section" data-tour={tourId} data-testid={testId}>
      <Group
        gap="xs"
        wrap="nowrap"
        {...(flat
          ? {}
          : {
              style: { cursor: "pointer" },
              onClick: () => setOpen((o) => !o),
              "data-testid": `${testId}-toggle`,
              role: "button",
              "aria-expanded": open,
            })}
      >
        {!flat && (
          <ActionIcon variant="subtle" size="sm" aria-hidden>
            {open ? "−" : "+"}
          </ActionIcon>
        )}
        <Text fw={600} size="sm">
          {title}
        </Text>
        {badge && (
          <Badge size="xs" variant="light" color="grape">
            {badge}
          </Badge>
        )}
        {info && (
          <Tip text={info.text}>
            <ActionIcon
              component="span"
              variant="subtle"
              color="gray"
              size="xs"
              role="button"
              tabIndex={0}
              aria-label={info.label}
              data-testid={`${testId}-info`}
              // The icon sits in the toggle row; using it must not also open/close the section.
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            >
              <CircleHelp size={14} aria-hidden />
            </ActionIcon>
          </Tip>
        )}
      </Group>
      <Collapse in={open}>
        <FormLayout
          style={{
            paddingTop: "var(--mantine-spacing-xs)",
            // Flat, it is a heading over the tab's own fields, which start where it starts.
            paddingInline: flat ? 0 : "var(--mantine-spacing-md)",
          }}
        >
          {children}
        </FormLayout>
      </Collapse>
    </div>
  );
}
