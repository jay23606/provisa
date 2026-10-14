// Copyright (c) 2026 Kenneth Stott
// Canary: 24cab9c9-d575-4e1c-939b-d6bb760d4a9c
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A call handed to the OpenAPI docs with autoRun (NL "Open in OpenAPI", Polly) is opened in the
// docs, whether the page was just opened or was already open.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, useNavigate } from "react-router-dom";

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    role: { id: "org_admin" },
    selectedRoles: [{ id: "org_admin" }],
    loading: false,
  }),
}));
vi.mock("../context/DomainFilterContext", () => ({
  useDomainFilter: () => ({ checkedDomains: new Set<string>() }),
}));

import { OpenApiPage } from "../pages/OpenApiPage";

function Polly({ path }: { path: string }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() =>
        navigate("/openapi", { state: { openApiUrl: `GET /data/rest${path}`, autoRun: true } })
      }
    >
      {path}
    </button>
  );
}

/** Swagger UI's operation blocks, as the drive routine finds them; records each one opened. */
function stockDocs(doc: Document, opened: string[]) {
  doc.body.innerHTML = ["/pet-store/users", "/pet-store/inquiries"]
    .map(
      (p) => `<div class="opblock"><span class="opblock-summary-method">GET</span>
        <span data-path="${p}"></span><button class="opblock-summary-control"></button></div>`,
    )
    .join("");
  doc.querySelectorAll(".opblock").forEach((block) => {
    block.querySelector("button")!.addEventListener("click", () => {
      opened.push(block.querySelector("[data-path]")!.getAttribute("data-path")!);
      block.classList.add("is-open");
    });
  });
}

describe("OpenApiPage — a hand-off while the page is open", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html><body></body></html>", { status: 200 })),
    );
  });

  it("opens each handed call in the docs", async () => {
    const opened: string[] = [];
    const { container } = render(
      <MantineProvider>
        <MemoryRouter initialEntries={["/openapi"]}>
          <Polly path="/pet-store/users" />
          <Polly path="/pet-store/inquiries" />
          <OpenApiPage />
        </MemoryRouter>
      </MantineProvider>,
    );
    const frame = await waitFor(() => {
      const f = container.querySelector("iframe");
      expect(f).not.toBeNull();
      return f as HTMLIFrameElement;
    });
    // jsdom lays nothing out, so the frame's own elements cannot scroll.
    (
      frame.contentWindow as unknown as { Element: typeof Element }
    ).Element.prototype.scrollIntoView = () => undefined;
    stockDocs(frame.contentDocument!, opened);
    fireEvent.load(frame);

    act(() => screen.getByText("/pet-store/users").click());
    await waitFor(() => expect(opened).toContain("/pet-store/users"));

    act(() => screen.getByText("/pet-store/inquiries").click());
    await waitFor(() => expect(opened).toContain("/pet-store/inquiries"));
  });
});

describe("OpenApiPage — a handed call's response (REQ-2010)", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html><body></body></html>", { status: 200 })),
    );
  });

  it("marks the page answered once the call's response is in, and not before", async () => {
    const { container } = render(
      <MantineProvider>
        <MemoryRouter initialEntries={["/openapi"]}>
          <Polly path="/pet-store/users" />
          <OpenApiPage />
        </MemoryRouter>
      </MantineProvider>,
    );
    const frame = await waitFor(() => {
      const f = container.querySelector("iframe");
      expect(f).not.toBeNull();
      return f as HTMLIFrameElement;
    });
    (
      frame.contentWindow as unknown as { Element: typeof Element }
    ).Element.prototype.scrollIntoView = () => undefined;
    const doc = frame.contentDocument!;
    // One operation whose Execute answers only when the test says so.
    doc.body.innerHTML = `<div class="opblock"><span class="opblock-summary-method">GET</span>
      <span data-path="/pet-store/users"></span><button class="opblock-summary-control"></button>
      <button class="btn execute opblock-control__btn"></button><div class="responses-wrapper"></div></div>`;
    let executed = false;
    doc.querySelector(".execute")!.addEventListener("click", () => {
      executed = true;
    });
    fireEvent.load(frame);
    const page = container.querySelector(".openapi-page")!;

    act(() => screen.getByText("/pet-store/users").click());
    await waitFor(() => expect(executed).toBe(true));
    expect(page.hasAttribute("data-answered")).toBe(false);
    doc.querySelector(".responses-wrapper")!.innerHTML = '<pre class="microlight">[]</pre>';
    await waitFor(() => expect(page.hasAttribute("data-answered")).toBe(true));
  });
});
