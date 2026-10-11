// Copyright (c) 2026 Kenneth Stott
// Canary: 561c87e8-4176-4cba-8474-39dcd7a18de3
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A list with a detail panel on its right: the panel is there only while it has content; it
// closes by its button, by Escape and by its caller; its left edge resizes it by pointer and by
// keyboard and the width is kept; it expands to the whole row and back; on a row too narrow for
// both, the list gives way; what the content puts in PanelActions sits in the panel's head.

import { useState } from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "../../../test-utils/render";
import { PanelActions, SplitPane } from "../SplitPane";

const KEY = "provisa.test.splitWidth";
const LABELS = {
  panel: "Table details",
  resize: "Resize the detail panel",
  expand: "Expand the panel",
  restore: "Restore the panel",
  close: "Close the detail panel",
  backToList: "Back to the list",
};

function Page({ closeOnEscape }: { closeOnEscape?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <SplitPane
      testId="split"
      storageKey={KEY}
      labels={LABELS}
      title={open}
      onClose={() => setOpen(null)}
      closeOnEscape={closeOnEscape}
      list={
        <>
          <button onClick={() => setOpen("orders")}>orders</button>
          <button onClick={() => setOpen("customers")}>customers</button>
        </>
      }
    >
      {open === null ? null : (
        <div>
          detail of {open}
          <PanelActions>
            <button>Preview {open}</button>
          </PanelActions>
        </div>
      )}
    </SplitPane>
  );
}

/** jsdom lays nothing out: give an element the size a browser would report. */
function size(el: Element, props: Record<string, number>) {
  for (const [name, value] of Object.entries(props)) {
    Object.defineProperty(el, name, { configurable: true, value });
  }
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1500 });
});

describe("SplitPane", () => {
  it("opens on a row, swaps to another, and shows which is open in its head", () => {
    render(<Page />);
    expect(screen.queryByTestId("split-panel")).toBeNull();
    expect(screen.queryByRole("separator")).toBeNull();

    fireEvent.click(screen.getByText("orders"));
    const panel = screen.getByRole("complementary", { name: "Table details" });
    expect(panel).toHaveTextContent("detail of orders");
    expect(screen.getByTestId("split-title")).toHaveTextContent("orders");
    expect(screen.getByRole("separator", { name: "Resize the detail panel" })).toBeInTheDocument();

    fireEvent.click(screen.getByText("customers"));
    expect(screen.getByTestId("split-panel")).toHaveTextContent("detail of customers");
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
  });

  it("puts the content's actions in the pinned head", () => {
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    const head = screen.getByTestId("split-title").parentElement as HTMLElement;
    expect(within(head).getByRole("button", { name: "Preview orders" })).toBeInTheDocument();
  });

  it("closes by its button and by Escape", () => {
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    fireEvent.click(screen.getByTestId("split-close"));
    expect(screen.queryByTestId("split-panel")).toBeNull();

    fireEvent.click(screen.getByText("orders"));
    fireEvent.keyDown(screen.getByTestId("split-panel"), { key: "Escape" });
    expect(screen.queryByTestId("split-panel")).toBeNull();
  });

  it("leaves Escape alone while leaving would drop what is being typed", () => {
    render(<Page closeOnEscape={false} />);
    fireEvent.click(screen.getByText("orders"));
    fireEvent.keyDown(screen.getByTestId("split-panel"), { key: "Escape" });
    expect(screen.getByTestId("split-panel")).toBeInTheDocument();
  });

  it("takes focus when it opens and gives it back when it closes", () => {
    render(<Page />);
    const row = screen.getByText("orders");
    row.focus();
    fireEvent.click(row);
    expect(screen.getByTestId("split-panel")).toHaveFocus();
    fireEvent.click(screen.getByTestId("split-close"));
    expect(row).toHaveFocus();
  });

  it("opens at about 60% of the window and keeps the width it is dragged to", () => {
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    const panel = screen.getByTestId("split-panel");
    expect(panel.style.width).toBe("900px");
    size(screen.getByTestId("split"), { clientWidth: 1452 });
    panel.getBoundingClientRect = vi.fn(() => ({ right: 1476 }) as DOMRect);
    // The panel's right edge stays put; its left edge follows the pointer.
    fireEvent.pointerDown(screen.getByTestId("split-handle"), { clientX: 576 });
    fireEvent.pointerMove(window, { clientX: 776 });
    fireEvent.pointerUp(window);
    expect(panel.style.width).toBe("700px");
    expect(localStorage.getItem(KEY)).toBe("700");
  });

  it("never squeezes the list or the panel below what each needs", () => {
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    const panel = screen.getByTestId("split-panel");
    size(screen.getByTestId("split"), { clientWidth: 1452 });
    panel.getBoundingClientRect = vi.fn(() => ({ right: 1476 }) as DOMRect);
    fireEvent.pointerDown(screen.getByTestId("split-handle"), { clientX: 576 });
    fireEvent.pointerMove(window, { clientX: -4000 });
    expect(panel.style.width).toBe("1172px"); // the row less the list's 280
    fireEvent.pointerMove(window, { clientX: 4000 });
    expect(panel.style.width).toBe("360px");
    fireEvent.pointerUp(window);
  });

  it("is resized from the keyboard with the arrow keys", () => {
    localStorage.setItem(KEY, "700");
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    size(screen.getByTestId("split"), { clientWidth: 1452 });
    const handle = screen.getByTestId("split-handle");
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(screen.getByTestId("split-panel").style.width).toBe("732px");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(screen.getByTestId("split-panel").style.width).toBe("700px");
  });

  it("expands to the whole row, putting the list away, and comes back", () => {
    render(<Page />);
    fireEvent.click(screen.getByText("orders"));
    const list = screen.getByText("customers").parentElement as HTMLElement;
    fireEvent.click(screen.getByRole("button", { name: "Expand the panel" }));
    expect(list).not.toBeVisible();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.getByTestId("split-panel").style.width).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Restore the panel" }));
    expect(list).toBeVisible();
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("gives the row to the panel, with a way back, where both do not fit", () => {
    const observed: (() => void)[] = [];
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(cb: () => void) {
        observed.push(cb);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    try {
      render(<Page />);
      size(screen.getByTestId("split"), { clientWidth: 872 }); // a 1280 window with Polly open
      fireEvent.click(screen.getByText("orders"));
      // The row reports its width once it has been measured.
      act(() => observed.forEach((cb) => cb()));
      const back = screen.getByRole("button", { name: "Back to the list" });
      expect(screen.getByText("customers").parentElement).not.toBeVisible();
      expect(screen.queryByRole("separator")).toBeNull();
      expect(screen.queryByRole("button", { name: "Expand the panel" })).toBeNull();
      fireEvent.click(back);
      expect(screen.queryByTestId("split-panel")).toBeNull();
      expect(screen.getByText("customers").parentElement).toBeVisible();
    } finally {
      globalThis.ResizeObserver = original;
    }
  });
});
