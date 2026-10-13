// Copyright (c) 2026 Kenneth Stott
// Canary: d9766d17-4276-4236-8a21-d295340e93b7
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2008: what the UI saves in the browser is saved per control plane and org.

import { afterEach, describe, expect, it } from "vitest";
import {
  bindStorageScope,
  getStored,
  removeStored,
  removeStoredEverywhere,
  scopedStorage,
  setStored,
  storageKey,
  storedKeys,
} from "../lib/browserStorage";

const DEMO_A = { controlPlaneId: "cp-a", orgId: "acme" };
const DEMO_B = { controlPlaneId: "cp-b", orgId: "acme" };

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("browser storage per control plane and org", () => {
  it("names a key by control plane, org and key", () => {
    bindStorageScope(DEMO_A);
    expect(storageKey("provisa.collapsibles")).toBe("cp-a:acme:provisa.collapsibles");
    bindStorageScope({ controlPlaneId: "cp-a", orgId: null });
    expect(storageKey("provisa.collapsibles")).toBe("cp-a::provisa.collapsibles");
  });

  it("keeps each control plane's and org's value apart, and finds it again on return", () => {
    bindStorageScope(DEMO_A);
    setStored("k", "a");
    bindStorageScope(DEMO_B);
    expect(getStored("k")).toBeNull();
    setStored("k", "b");
    bindStorageScope({ controlPlaneId: "cp-a", orgId: "globex" });
    expect(getStored("k")).toBeNull();
    bindStorageScope(DEMO_A);
    expect(getStored("k")).toBe("a");
    removeStored("k");
    expect(getStored("k")).toBeNull();
    bindStorageScope(DEMO_B);
    expect(getStored("k")).toBe("b");
  });

  it("saves a global key for the browser as a whole", () => {
    bindStorageScope(DEMO_A);
    setStored("provisa_token", "t", { global: true });
    bindStorageScope(DEMO_B);
    expect(getStored("provisa_token", { global: true })).toBe("t");
    expect(localStorage.getItem("provisa_token")).toBe("t");
  });

  it("keeps sessionStorage per scope too, and lists the scope's keys", () => {
    bindStorageScope(DEMO_A);
    setStored("introspection:x", "1", { session: true });
    setStored("other", "1", { session: true });
    bindStorageScope(DEMO_B);
    setStored("introspection:y", "1", { session: true });
    expect(storedKeys({ session: true })).toEqual(["introspection:y"]);
    bindStorageScope(DEMO_A);
    expect(storedKeys({ session: true }).sort()).toEqual(["introspection:x", "other"]);
    expect(getStored("introspection:x")).toBeNull(); // localStorage holds none of it
  });

  it("removes a session's key from every scope, and only that key", () => {
    bindStorageScope(DEMO_A);
    setStored("provisa.checkedDomains", "[]");
    setStored("provisa.checkedDomainsX", "[]");
    bindStorageScope(DEMO_B);
    setStored("provisa.checkedDomains", "[]");
    localStorage.setItem("provisa.checkedDomains", "global");
    removeStoredEverywhere("provisa.checkedDomains");
    expect(getStored("provisa.checkedDomains")).toBeNull();
    bindStorageScope(DEMO_A);
    expect(getStored("provisa.checkedDomains")).toBeNull();
    expect(getStored("provisa.checkedDomainsX")).toBe("[]");
    expect(localStorage.getItem("provisa.checkedDomains")).toBe("global");
  });

  it("gives GraphiQL a storage of the scope, so each scope has its own explorer tabs", () => {
    const graphiql = scopedStorage("graphiql:");
    bindStorageScope(DEMO_A);
    graphiql.setItem("graphiql:tabState", "pets");
    setStored("unrelated", "1");
    bindStorageScope(DEMO_B);
    expect(graphiql.getItem("graphiql:tabState")).toBeNull();
    graphiql.setItem("graphiql:tabState", "weblogs");
    expect(graphiql.length).toBe(1);
    bindStorageScope(DEMO_A);
    expect(graphiql.getItem("graphiql:tabState")).toBe("pets");
    graphiql.clear();
    expect(graphiql.getItem("graphiql:tabState")).toBeNull();
    expect(getStored("unrelated")).toBe("1");
    bindStorageScope(DEMO_B);
    expect(graphiql.getItem("graphiql:tabState")).toBe("weblogs");
  });

  it("refuses a scoped key while no control plane is bound", () => {
    bindStorageScope(null);
    expect(() => getStored("k")).toThrow(/saved per control plane and organization/);
    expect(getStored("provisa_token", { global: true })).toBeNull();
  });
});
