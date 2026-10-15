// Copyright (c) 2026 Kenneth Stott
// Canary: 291150bf-5c6f-41c9-86dc-a66ac3b261bc
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1363: the domain tree as the pages read it. A domain names at most one parent; a role
// that lists a domain reaches every domain under it. The server holds the rule (it refuses an
// unknown parent and a cycle, and does the flattening); these helpers only read the tree.

export interface TreeDomain {
  id: string;
  parentDomainId?: string | null;
}

/** Every domain under `id`, at any depth. `id` itself is not among them. */
export function descendantsOf(id: string, domains: TreeDomain[]): string[] {
  const out: string[] = [];
  const frontier = [id];
  while (frontier.length > 0) {
    const parent = frontier.pop();
    for (const d of domains) {
      if (d.parentDomainId === parent && !out.includes(d.id) && d.id !== id) {
        out.push(d.id);
        frontier.push(d.id);
      }
    }
  }
  return out.sort();
}

/** The domains a grant reaches beyond the ones it lists: everything under them. */
export function alsoReached(listed: string[], domains: TreeDomain[]): string[] {
  const reached = new Set<string>();
  for (const id of listed) descendantsOf(id, domains).forEach((d) => reached.add(d));
  listed.forEach((id) => reached.delete(id));
  return [...reached].sort();
}
