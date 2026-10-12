// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A registered source's panel reads its settings as its edit form has them: every field a
// registered source's form shows, the description it has (none is not filled in for it), a
// secret as set, and a registration a remote API source's list does not hold named as an error.

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "../../test-utils/render";
import userEvent from "@testing-library/user-event";
import type { Source } from "../../types/admin";

vi.mock("../../api/admin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/admin")>()),
  fetchSettings: vi.fn().mockResolvedValue({
    redirect: { enabled: false, threshold: 10000, default_format: "json", ttl: 3600 },
    sampling: { default_sample_size: 1000 },
    cache: { default_ttl: 300 },
    naming: { domain_prefix: false, convention: "none" },
  }),
  fetchFederationEngine: vi.fn().mockResolvedValue(null),
}));

vi.mock("../../context/AuthContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../context/AuthContext")>()),
  useAuth: () => ({
    role: "admin",
    selectedRoles: ["admin"],
    capabilities: ["admin"],
    domainAccess: ["*"],
  }),
}));

let SOURCES: Source[] = [];

vi.mock("../../hooks/useAdminQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../hooks/useAdminQueries")>()),
  useSources: () => ({ sources: SOURCES, loading: false, refetch: vi.fn().mockResolvedValue({}) }),
  useDomains: () => ({ domains: [], loading: false, refetch: vi.fn() }),
}));

import { SourcesPage } from "../SourcesPage";

function source(overrides: Partial<Source>): Source {
  return {
    id: "sales",
    type: "postgresql",
    host: "db.example.test",
    port: 5432,
    database: "sales",
    username: "reader",
    passwordRef: "${secret:sales}",
    description: "",
    cacheEnabled: true,
    cacheTtl: 300,
    allowedDomains: [],
    changeSignal: "ttl",
    ...overrides,
  } as unknown as Source;
}

function valueOf(label: string): string | null | undefined {
  const dt = [...screen.getByTestId("source-read").querySelectorAll("dt")].find(
    (d) => d.textContent === label,
  );
  return dt?.nextElementSibling?.textContent;
}

describe("a registered source's read view", () => {
  it("reads every field of a registered source's form, as the source has it", async () => {
    SOURCES = [source({})];
    render(<SourcesPage />);
    await userEvent.click(await screen.findByTestId("sources-row-sales"));
    await screen.findByTestId("source-read");
    expect(valueOf("Host")).toBe("db.example.test");
    expect(valueOf("Password")).toBe("Set");
    // Not the description a new source is given from its type: this one has none.
    expect(valueOf("Description")).toBe("—");
    // A registered source's form has its naming convention; Inherit is a value, not empty.
    expect(valueOf("Naming Convention")).toBe("Inherit (global)");
    expect(valueOf("Allowed Domains")).toBe("—");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("names the registration list that does not hold a remote API source", async () => {
    SOURCES = [source({ id: "pets", type: "openapi", host: null, path: "https://x.test" })];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("[]", { status: 200 })),
    );
    render(<SourcesPage />);
    await userEvent.click(await screen.findByTestId("sources-row-pets"));
    expect(
      await screen.findByText(/\/admin\/openapi\/list holds no registration for source pets/),
    ).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
