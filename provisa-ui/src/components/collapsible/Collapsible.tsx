// Copyright (c) 2026 Kenneth Stott
// Canary: ac301480-5f36-4957-a1dd-f0ae10a2fc0e
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import {
  Children,
  createContext,
  Fragment,
  isValidElement,
  useContext,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { Accordion } from "@mantine/core";
import { readCollapsibleStates, writeCollapsibleState } from "./collapsibleState";
import "./collapsible.css";

/**
 * The one collapsible of the application: every collapsible panel is an item of a `Collapsibles`,
 * so all look alike open and closed (collapsible.css) and each opens as this viewer left it.
 */
export interface CollapsibleItemProps {
  /** The item's id within its `Collapsibles`: with the group's id, the panel's stable id. */
  value: string;
  /** The heading the item opens and closes by. */
  title: ReactNode;
  /** Open when this viewer has never opened or closed it. */
  defaultOpen?: boolean;
  /** Held open whatever was remembered: the panel holds something that needs attention. */
  forceOpen?: boolean;
  testId?: string;
  controlTestId?: string;
  /** Its content is mounted only while it is open: a panel whose content reads something when
   *  mounted (a deployment's configuration, a key's state) reads it only when looked at. */
  mountWhenOpen?: boolean;
  children: ReactNode;
}

/** The items of the `Collapsibles` around an item that are open. */
const OpenItems = createContext<ReadonlySet<string>>(new Set());

/** One panel of a `Collapsibles`: its heading, then its content while open. */
export function CollapsibleItem({
  value,
  title,
  testId,
  controlTestId,
  mountWhenOpen = false,
  children,
}: CollapsibleItemProps) {
  const open = useContext(OpenItems);
  return (
    <Accordion.Item value={value} data-testid={testId}>
      <Accordion.Control data-testid={controlTestId ?? `${value}-toggle`}>
        {title}
      </Accordion.Control>
      <Accordion.Panel>{mountWhenOpen && !open.has(value) ? null : children}</Accordion.Panel>
    </Accordion.Item>
  );
}

CollapsibleItem.collapsibleItem = true;

/** The `CollapsibleItem`s among ``children``, through fragments and lists. */
function items(children: ReactNode): ReactElement<CollapsibleItemProps>[] {
  const found: ReactElement<CollapsibleItemProps>[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    if (child.type === Fragment) {
      found.push(...items((child.props as { children?: ReactNode }).children));
    } else if ((child.type as { collapsibleItem?: boolean }).collapsibleItem) {
      // A CollapsibleItem, or a component that renders one (FormFold): its props name the item, and
      // a static ``defaultOpen`` on the component is its default where the props give none.
      found.push(child as ReactElement<CollapsibleItemProps>);
    }
  });
  return found;
}

/**
 * Collapsible panels, each open or closed on its own. ``id`` names the group where it is (a page
 * and its panel, e.g. ``admin.ai-models``): with each item's value it is the key the viewer's open
 * and closed state is kept under, so the panels open again as they were left.
 */
export function Collapsibles({
  id,
  reveal,
  children,
  testId,
}: {
  id: string;
  /** An item to open, when a link asks for it (``?section=``): opened, and remembered so. */
  reveal?: string | null;
  children: ReactNode;
  testId?: string;
}) {
  const [remembered, setRemembered] = useState<Record<string, boolean>>(() => {
    const held = readCollapsibleStates()[id] ?? {};
    return reveal ? { ...held, [reveal]: true } : held;
  });
  const [revealed, setRevealed] = useState(reveal);
  if (reveal !== revealed) {
    // A link that asks for another item opens it too.
    setRevealed(reveal);
    if (reveal) setRemembered((held) => ({ ...held, [reveal]: true }));
  }
  const found = items(children);
  const open = found
    .filter(
      (item) =>
        item.props.forceOpen ||
        (remembered[item.props.value] ??
          item.props.defaultOpen ??
          (item.type as { defaultOpen?: boolean }).defaultOpen ??
          true),
    )
    .map((item) => item.props.value);
  const onChange = (values: string[]) => {
    const next: Record<string, boolean> = {};
    for (const item of found) next[item.props.value] = values.includes(item.props.value);
    setRemembered((held) => ({ ...held, ...next }));
    writeCollapsibleState(id, next);
  };
  return (
    <Accordion
      multiple
      variant="contained"
      className="provisa-collapsible"
      value={open}
      onChange={onChange}
      data-testid={testId}
      data-collapsible-id={id}
    >
      <OpenItems.Provider value={new Set(open)}>{children}</OpenItems.Provider>
    </Accordion>
  );
}
