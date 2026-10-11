// Copyright (c) 2026 Kenneth Stott
// Canary: 2702cbfe-15e7-424f-a749-a50f720dd4cc
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The one tooltip of the application. Every hint shown on hover or keyboard focus is drawn by
// this file, on one surface (`.tip-surface` in App.css): a one-line `Tip`, and the titled card
// `HelpBubble` builds on it. No other file imports Mantine's Tooltip or HoverCard, and no control
// carries a native `title`; tipGuard.test.ts holds that.
//
// It costs nothing until it is needed: the target is rendered as it is, with three listeners, and
// the floating element is mounted the first time the pointer enters or the keyboard focuses it. A
// list of two hundred rows with a hint in several cells therefore mounts no popover at all.

import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";
import { Tooltip, type FloatingPosition } from "@mantine/core";
import { useMergedRef } from "@mantine/hooks";

/** Long enough that a pointer crossing a toolbar opens nothing, short enough not to be waited for. */
export const TIP_OPEN_DELAY_MS = 150;
/** The width a hint wraps at; a titled card is this wide. */
export const TIP_MAX_WIDTH = 340;

type TargetProps = {
  ref?: Ref<HTMLElement>;
  onMouseEnter?: (e: MouseEvent<HTMLElement>) => void;
  onMouseLeave?: (e: MouseEvent<HTMLElement>) => void;
  onFocus?: (e: FocusEvent<HTMLElement>) => void;
  onBlur?: (e: FocusEvent<HTMLElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLElement>) => void;
  "aria-describedby"?: string;
};

/**
 * The surface, attached to one element. `content` is what it shows; `card` gives it the titled
 * card's fixed width and padding. Opens on hover after `openDelay` and at once on keyboard focus;
 * Escape, blur and pointer-leave close it. The target is described by it (aria-describedby) and
 * keeps the accessible name it had.
 */
export function TipSurface({
  content,
  children,
  position = "top",
  card = false,
  openDelay = TIP_OPEN_DELAY_MS,
  testId,
}: {
  content: ReactNode;
  /** One element that takes a ref and mouse/focus handlers. */
  children: ReactElement<TargetProps>;
  position?: FloatingPosition;
  card?: boolean;
  openDelay?: number;
  testId?: string;
}) {
  const id = useId();
  const [target, setTarget] = useState<HTMLElement | null>(null);
  // Mounted on first need and kept: the description stays attached to the target afterwards.
  const [armed, setArmed] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const cancel = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => cancel, [cancel]);

  const show = (delay: number) => {
    cancel();
    setArmed(true);
    if (delay === 0) setOpen(true);
    else timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    cancel();
    setOpen(false);
  };

  const own = children.props;
  // The target's element, kept here and handed on to whatever ref the target already had.
  const attach = useMergedRef<HTMLElement>(setTarget, own.ref);
  const describedBy = [own["aria-describedby"], armed ? id : undefined].filter(Boolean).join(" ");
  return (
    <>
      {/* eslint-disable-next-line react-hooks/refs --
          cloning one element to give it a ref and listeners is the documented way to attach a
          tooltip to a target (the library's own Tooltip does the same); nothing reads a ref's
          current value during render here. */}
      {cloneElement(children, {
        ref: attach,
        onMouseEnter: (e) => {
          own.onMouseEnter?.(e);
          show(openDelay);
        },
        onMouseLeave: (e) => {
          own.onMouseLeave?.(e);
          hide();
        },
        onFocus: (e) => {
          own.onFocus?.(e);
          // A click focuses too; only a focus the keyboard made shows the hint at once.
          if (e.currentTarget.matches(":focus-visible")) show(0);
        },
        onBlur: (e) => {
          own.onBlur?.(e);
          hide();
        },
        onKeyDown: (e) => {
          own.onKeyDown?.(e);
          if (e.key === "Escape") hide();
        },
        "aria-describedby": describedBy || undefined,
      })}
      {armed && (
        <Tooltip
          target={target}
          opened={open}
          keepMounted
          // The floating element takes an id of its own from the library, so what describes the
          // target is the text inside it, under the id this component chose.
          label={<div id={id}>{content}</div>}
          position={position}
          withArrow
          arrowSize={8}
          offset={8}
          multiline
          w={card ? TIP_MAX_WIDTH : undefined}
          maw={TIP_MAX_WIDTH}
          classNames={{ tooltip: card ? "tip-surface tip-surface--card" : "tip-surface" }}
          data-testid={testId}
        />
      )}
    </>
  );
}

/** A one-line hint on a control or on text. The target keeps its own accessible name. */
export function Tip({
  text,
  children,
  position,
  testId,
}: {
  text: string;
  children: ReactElement<TargetProps>;
  position?: FloatingPosition;
  testId?: string;
}) {
  return (
    <TipSurface content={text} position={position} testId={testId}>
      {children}
    </TipSurface>
  );
}
