// Copyright (c) 2026 Kenneth Stott
// Canary: 06c5e62b-9645-4bc5-9f5e-b1b6eb2ec2e9
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2006: a demo sandbox is opened from /demos/<name> with no sign-in and handed to its own
// address with the visitor's token; its welcome notice names every limit it runs under, each with

// REQ-2006: a live demo runs as its own anonymous visitor -- the token opening its sandbox gave --
// and never as a Provisa login the browser also holds. The visit reads, uses and changes none of
// the signed-in session (its token, org, role); ending it gives the person their own session back
// unchanged.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/firebase", () => ({
  // A Firebase login, live in this browser: what a visit must never send.
  currentFirebaseToken: () => Promise.resolve("firebase-login-token"),
}));

import { openDemoSandbox } from "../api/demoSandbox";
import { installAuthFetch } from "../lib/authFetch";
import { endVisit, getStored, setStored, visitorActive } from "../lib/browserStorage";
import { adoptSandboxTokenFromLocation } from "../lib/sandboxSession";
import { clearSessionState } from "../lib/session";
import { storedToken } from "../lib/sessionToken";

const LOGIN = { provisa_token: "login-token", provisa_org: "acme", provisa_role: "org_admin" };

/** The browser's own signed-in session, as localStorage holds it. */
function login(): Record<string, string | null> {
  return Object.fromEntries(Object.keys(LOGIN).map((k) => [k, localStorage.getItem(k)]));
}

function visit(): void {
  const location = {
    hash: "#provisa_sandbox=provisa_pat_visitor&provisa_sandbox_org=sbx0123456789ab",
    pathname: "/",
    search: "",
  };
  expect(adoptSandboxTokenFromLocation(location as Location)).toBe(true);
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  for (const [k, v] of Object.entries(LOGIN)) localStorage.setItem(k, v);
});
afterEach(() => endVisit());

describe("a live demo's visitor, in a browser signed in to Provisa", () => {
  it("is who the demo runs as: its token and org, not the login's", () => {
    visit();
    expect(visitorActive()).toBe(true);
    expect(storedToken()).toBe("provisa_pat_visitor");
    expect(getStored("provisa_org", { global: true })).toBe("sbx0123456789ab");
    expect(getStored("provisa_role", { global: true })).toBeNull(); // the login's role is not read
    expect(login()).toEqual(LOGIN); // and nothing of the login was changed
  });

  it("sends the visitor's token on every request, never the login's, Firebase's included", async () => {
    const sent: Headers[] = [];
    const underlying = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent.push(new Headers(init?.headers));
      return new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", underlying);
    window.fetch = underlying as unknown as typeof fetch;
    visit();
    installAuthFetch();
    await window.fetch("/auth/me");
    expect(sent[0].get("authorization")).toBe("Bearer provisa_pat_visitor");
    expect(sent[0].get("x-org-provisa")).toBe("sbx0123456789ab");
    vi.unstubAllGlobals();
  });

  it("is opened anonymously: the login held in the browser is not sent", async () => {
    const sent: Headers[] = [];
    const underlying = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent.push(new Headers(init?.headers));
      return new Response(JSON.stringify({ org_id: "sbx1", demo: "weblogs", token: "t" }), {
        status: 200,
      });
    });
    vi.stubGlobal("fetch", underlying);
    window.fetch = underlying as unknown as typeof fetch;
    installAuthFetch();
    await window.fetch("/auth/me"); // the login does ride on the browser's other requests
    expect(sent[0].get("authorization")).toBe("Bearer firebase-login-token");
    await openDemoSandbox("weblogs");
    expect(String(underlying.mock.calls[1][0])).toMatch(/\/public\/demos\/weblogs$/);
    expect(sent[1].get("authorization")).toBeNull();
    expect(sent[1].get("x-org-provisa")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("keeps its own role: choosing one in the demo leaves the login's as it was", () => {
    visit();
    setStored("provisa_role", "analyst", { global: true });
    expect(getStored("provisa_role", { global: true })).toBe("analyst");
    expect(localStorage.getItem("provisa_role")).toBe("org_admin");
  });

  it("ends with the person's own signed-in session, unchanged", () => {
    visit();
    setStored("provisa_role", "analyst", { global: true });
    clearSessionState(); // signing out of the demo
    expect(visitorActive()).toBe(false);
    expect(storedToken()).toBe("login-token");
    expect(getStored("provisa_org", { global: true })).toBe("acme");
    expect(login()).toEqual(LOGIN);
  });
});
