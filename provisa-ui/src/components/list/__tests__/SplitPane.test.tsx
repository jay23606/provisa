// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A list with a detail panel on its right: the panel is there only when it has content, the rule
// between the two resizes it by mouse and by keyboard, and its width is remembered.

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SplitPane } from "../SplitPane";

const KEY = "provisa.test.splitWidth";

function mount(panel: React.ReactNode | null) {
  return render(
    <SplitPane
      testId="split"
      storageKey={KEY}
      handleLabel="Resize the detail panel"
      panelLabel="Table details"
      list={<div>the list</div>}
      panel={panel}
    />,
  );
}

/** jsdom lays nothing out: give the panel the width a browser would report. */
function widthOf(el: HTMLElement, px: number) {
  Object.defineProperty(el, "offsetWidth", { configurable: true, value: px });
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
});

describe("SplitPane", () => {
  it("shows the list alone until there is something for the panel", () => {
    const { rerender } = mount(null);
    expect(screen.getByText("the list")).toBeInTheDocument();
    expect(screen.queryByTestId("split-panel")).toBeNull();
    expect(screen.queryByRole("separator")).toBeNull();
    rerender(
      <SplitPane
        testId="split"
        storageKey={KEY}
        handleLabel="Resize the detail panel"
        panelLabel="Table details"
        list={<div>the list</div>}
        panel={<div>the detail</div>}
      />,
    );
    expect(screen.getByTestId("split-panel")).toHaveTextContent("the detail");
    expect(screen.getByRole("separator", { name: "Resize the detail panel" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Table details" })).toBeInTheDocument();
  });

  it("takes its share of the page until it is resized, then keeps the dragged width", () => {
    mount(<div>the detail</div>);
    const panel = screen.getByTestId("split-panel");
    expect(panel.style.width).toBe(""); // the stylesheet's share of the page
    widthOf(panel, 700);
    // The panel is on the right: dragging the rule 100px to the left widens it by 100px.
    fireEvent.mouseDown(screen.getByTestId("split-handle"), { clientX: 580 });
    fireEvent.mouseMove(window, { clientX: 480 });
    fireEvent.mouseUp(window);
    expect(panel.style.width).toBe("800px");
    expect(localStorage.getItem(KEY)).toBe("800");
  });

  it("never squeezes the list or the panel below what each needs", () => {
    mount(<div>the detail</div>);
    const panel = screen.getByTestId("split-panel");
    widthOf(panel, 700);
    fireEvent.mouseDown(screen.getByTestId("split-handle"), { clientX: 580 });
    fireEvent.mouseMove(window, { clientX: -2000 });
    expect(panel.style.width).toBe("1000px"); // 1280 less the list's 280
    fireEvent.mouseMove(window, { clientX: 5000 });
    expect(panel.style.width).toBe("360px");
    fireEvent.mouseUp(window);
  });

  it("is resized from the keyboard with the arrow keys", () => {
    mount(<div>the detail</div>);
    const panel = screen.getByTestId("split-panel");
    widthOf(panel, 700);
    const handle = screen.getByTestId("split-handle");
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(panel.style.width).toBe("732px");
    widthOf(panel, 732);
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(panel.style.width).toBe("700px");
  });

  it("opens at the width it was left at", () => {
    localStorage.setItem(KEY, "640");
    mount(<div>the detail</div>);
    expect(screen.getByTestId("split-panel").style.width).toBe("640px");
  });
});
