// Copyright (c) 2026 Kenneth Stott
// Canary: cfea2e0c-8756-49ca-a564-6d4f8067d35d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A list with a detail panel on its right: the list keeps the room the panel leaves, and the rule
// between them is the handle that resizes the panel. The panel's width is remembered per page.

import { useCallback, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { useLocalStorage } from "../graph/graph-persistence";

/** The narrowest the panel may be dragged, and the least room the list always keeps. */
const PANEL_MIN = 360;
const LIST_MIN = 280;
/** One press of an arrow key on the handle. */
const KEY_STEP = 32;

function clamp(width: number): number {
  return Math.max(PANEL_MIN, Math.min(window.innerWidth - LIST_MIN, width));
}

/**
 * `list` fills the page; when `panel` is given it opens on the right at 60% of the page until the
 * handle is dragged (or moved with the arrow keys), after which its width is kept under
 * `storageKey`.
 */
export function SplitPane({
  list,
  panel,
  storageKey,
  handleLabel,
  panelLabel,
  testId,
}: {
  list: ReactNode;
  panel: ReactNode | null;
  storageKey: string;
  handleLabel: string;
  panelLabel: string;
  testId: string;
}) {
  const [width, setWidth] = useLocalStorage<number | null>(storageKey, null);
  const panelRef = useRef<HTMLElement>(null);

  const startDrag = useCallback(
    (e: MouseEvent) => {
      e.preventDefault();
      const panelEl = panelRef.current;
      if (!panelEl) return;
      const startX = e.clientX;
      const startW = panelEl.offsetWidth;
      // The panel is on the right: dragging the handle left widens it.
      const onMove = (ev: globalThis.MouseEvent) => setWidth(clamp(startW - (ev.clientX - startX)));
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [setWidth],
  );

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const panelEl = panelRef.current;
    if (!panelEl) return;
    e.preventDefault();
    setWidth(clamp(panelEl.offsetWidth + (e.key === "ArrowLeft" ? KEY_STEP : -KEY_STEP)));
  };

  return (
    <div className="split-pane" data-testid={testId}>
      <div className="split-pane__list">{list}</div>
      {panel !== null && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={handleLabel}
            tabIndex={0}
            className="split-pane__handle"
            onMouseDown={startDrag}
            onKeyDown={onKeyDown}
            data-testid={`${testId}-handle`}
          >
            <div />
          </div>
          <aside
            ref={panelRef}
            className="split-pane__panel"
            aria-label={panelLabel}
            style={width === null ? undefined : { width }}
            data-testid={`${testId}-panel`}
          >
            {panel}
          </aside>
        </>
      )}
    </div>
  );
}
