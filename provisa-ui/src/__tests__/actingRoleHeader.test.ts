// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Rights follow the roles a request names, not every role the user holds: every request to the
// server -- admin as well as data -- carries the role picker's selection, the same one the UI's
// capability gates read.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/firebase", () => ({ currentFirebaseToken: vi.fn(async () => null) }));
vi.mock("../lib/sessionToken", () => ({ storedToken: vi.fn(() => "token-1") }));

import { installAuthFetch } from "../lib/authFetch";
import { ROLE_HEADER, setActingRoles } from "../lib/actingRole";

const original = window.fetch;
let seen: Headers | null = null;

beforeEach(() => {
  localStorage.clear();
  seen = null;
  setActingRoles(null);
  window.fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen = new Headers(init?.headers);
    return new Response("{}", { status: 200 });
  }) as typeof window.fetch;
  installAuthFetch();
});

afterEach(() => {
  window.fetch = original;
  setActingRoles(null);
});

describe("the acting roles header", () => {
  it("carries the selected roles on an admin request", async () => {
    setActingRoles("analyst,editor");
    await window.fetch("/admin/graphql", { method: "POST" });
    expect(seen?.get(ROLE_HEADER)).toBe("analyst,editor");
  });

  it("leaves a page that names its own role as it is", async () => {
    setActingRoles("analyst,editor");
    await window.fetch("/data/sql", { headers: { [ROLE_HEADER]: "editor" } });
    expect(seen?.get(ROLE_HEADER)).toBe("editor");
  });

  it("sends none before any role is known", async () => {
    await window.fetch("/auth/me");
    expect(seen?.get(ROLE_HEADER)).toBeNull();
  });

  it("is never sent to another origin", async () => {
    setActingRoles("analyst");
    await window.fetch("https://example.com/x");
    expect(seen?.get(ROLE_HEADER)).toBeNull();
  });
});
