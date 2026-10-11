// Copyright (c) 2026 Kenneth Stott
// Canary: 0874ac56-7ca9-4875-8268-77306128581d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1795: the width of a panel docked at the right of a row, resized by dragging its left edge
// and kept per browser. One mechanism for every such panel: Polly and a page's detail panel.

import { useRef, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useLocalStorage } from "../components/graph/graph-persistence";

/** One press of an arrow key on the resize handle. */
const KEY_STEP = 32;

export interface ResizableWidth<E extends HTMLElement> {
  /** Goes on the panel: the drag measures from the panel's own right edge. */
  ref: React.RefObject<E | null>;
  width: number;
  /** `onPointerDown` of the handle on the panel's left edge. */
  startResize: (e: ReactPointerEvent) => void;
  /** `onKeyDown` of the handle: the arrow keys move the edge. */
  onHandleKeyDown: (e: KeyboardEvent) => void;
}

/**
 * `max` may depend on what else shares the row, so it is asked for at the moment of the drag.
 * The width starts at `initial` and, once changed, is kept under `storageKey`.
 */
export function useResizableWidth<E extends HTMLElement>(
  storageKey: string,
  { initial, min, max }: { initial: number; min: number; max: number | (() => number) },
): ResizableWidth<E> {
  const [width, setWidth] = useLocalStorage(storageKey, initial);
  const ref = useRef<E | null>(null);
  const resizingRef = useRef(false);
  const clamp = (w: number) =>
    Math.min(typeof max === "function" ? max() : max, Math.max(min, Math.round(w)));

  const startResize = (e: ReactPointerEvent) => {
    const panel = ref.current;
    if (!panel) return;
    e.preventDefault();
    resizingRef.current = true;
    // The panel's right edge stays where it is; its left edge follows the pointer.
    const right = panel.getBoundingClientRect().right;
    const onMove = (ev: PointerEvent) => {
      if (!resizingRef.current) return;
      setWidth(clamp(right - ev.clientX));
    };
    const onUp = () => {
      resizingRef.current = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const onHandleKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    setWidth((w) => clamp(w + (e.key === "ArrowLeft" ? KEY_STEP : -KEY_STEP)));
  };

  return { ref, width, startResize, onHandleKeyDown };
}
