// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * REQ-2008: everything the UI saves in the browser is saved per control plane and organization,
 * under `<control plane id>:<org id>:<key>`, so each demo, instance and org keeps its own state:
 * switching to another carries nothing across, and coming back finds what was left there. The
 * control plane's id comes from `/auth/me`; AuthContext's scope gate binds it with the acting org
 * before any page mounts, and remounts the pages when either changes.
 *
 * A key saved for the browser as a whole says so with `{ global: true }`: the session's identity
 * (token, org, role, environment), which rides on the requests that establish the scope, and the
 * tour's offer, seen and declined marks.
 *
 * Every read and write of `localStorage` and `sessionStorage` goes through here
 * (src/__tests__/browserStorage.guard.test.ts).
 */

export interface StorageScope {
  controlPlaneId: string;
  /** `null` when acting in no org (a platform administrator before any org exists): the state
   * is then the control plane's own, saved under `<control plane id>::<key>`. */
  orgId: string | null;
}

export interface StoredKeyOptions {
  /** Saved for the browser as a whole, not per control plane and org. */
  global?: true;
  /** `sessionStorage` (this tab, until it closes) rather than `localStorage`. */
  session?: true;
}

let bound: StorageScope | null = null;

/** The scope the pages now save under; `null` unbinds it (no page is mounted then). */
export function bindStorageScope(scope: StorageScope | null): void {
  bound = scope;
}

export function storageScope(): StorageScope | null {
  return bound;
}

/** The key as the browser holds it. */
export function storageKey(key: string, options?: StoredKeyOptions): string {
  if (options?.global) return key;
  if (bound === null) {
    // The scope gate binds the scope before any page that saves state mounts; a read or write
    // before it is a defect, never a read of "nothing saved".
    throw new Error(
      `"${key}" is saved per control plane and organization, and neither is known yet`,
    );
  }
  return `${bound.controlPlaneId}:${bound.orgId ?? ""}:${key}`;
}

function area(options?: StoredKeyOptions): Storage {
  return options?.session ? window.sessionStorage : window.localStorage;
}

export function getStored(key: string, options?: StoredKeyOptions): string | null {
  return area(options).getItem(storageKey(key, options));
}

export function setStored(key: string, value: string, options?: StoredKeyOptions): void {
  area(options).setItem(storageKey(key, options), value);
}

export function removeStored(key: string, options?: StoredKeyOptions): void {
  area(options).removeItem(storageKey(key, options));
}

/** The keys saved in the bound scope (as passed to `getStored`), in the area named. */
export function storedKeys(options?: { session?: true }): string[] {
  const prefix = storageKey("", options);
  const store = area(options);
  const keys: string[] = [];
  for (let i = 0; i < store.length; i++) {
    const k = store.key(i);
    if (k !== null && k.startsWith(prefix)) keys.push(k.slice(prefix.length));
  }
  return keys;
}

/** Remove `key` from every control plane and org it was saved under in this browser: state that
 * must not outlive the session that saved it (REQ-1297, REQ-1349), whichever scope it was in. */
export function removeStoredEverywhere(key: string): void {
  const store = window.localStorage;
  const suffix = `:${key}`;
  const doomed: string[] = [];
  for (let i = 0; i < store.length; i++) {
    const k = store.key(i);
    // A scoped key is `<control plane>:<org>:<key>`: two separators before the key itself.
    if (k !== null && k.endsWith(suffix) && k.slice(0, -suffix.length).split(":").length === 2) {
      doomed.push(k);
    }
  }
  for (const k of doomed) store.removeItem(k);
}

/** A `Storage`-shaped view of the bound scope's `localStorage`, for a library that saves its own
 * state through a storage it is handed (GraphiQL's tabs, query history and headers): it saves in
 * the bound scope like everything else. `clear` and `length` cover the keys starting `prefix`,
 * the library's own namespace. */
export function scopedStorage(prefix: string): {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  clear(): void;
  readonly length: number;
} {
  const own = () => storedKeys().filter((k) => k.startsWith(prefix));
  return {
    getItem: (key) => getStored(key),
    setItem: (key, value) => setStored(key, value),
    removeItem: (key) => removeStored(key),
    clear: () => {
      for (const k of own()) removeStored(k);
    },
    get length() {
      return own().length;
    },
  };
}
