// Copyright (c) 2026 Kenneth Stott
// Canary: 03c5a85e-46e1-49a5-a2ca-b0ceed9c235e
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// What the server says of a source kind before anything is saved (/admin/source-kinds/{kind}).
// Each fact is a rule the server owns; the form asks rather than keep its own list of kinds:
// - cache_ttl_required: a source of the kind must state its Cache TTL itself -- every table of
//   it lands and refreshes by that one clock (REQ-1907);
// - sentinel_path: a source of the kind can have a sentinel marker (REQ-1148);
// - tables_land: every table of a source of the kind is served from a replica under the engine
//   bound here, so one registered under a ttl signal needs a Cache TTL, its own or its source's.

import { useEffect, useState } from "react";

export interface SourceKind {
  cache_ttl_required: boolean;
  sentinel_path: boolean;
  tables_land: boolean;
}

const asked = new Map<string, Promise<SourceKind>>();

/** Forget what was asked, so each kind is asked again (its facts follow the engine the server is
 * bound to, which a running deployment may change). */
export function forgetSourceKinds(): void {
  asked.clear();
}

/** The kind's facts, asked of the server once per kind. */
export function sourceKind(kind: string): Promise<SourceKind> {
  let answer = asked.get(kind);
  if (!answer) {
    answer = fetch(`/admin/source-kinds/${encodeURIComponent(kind)}`).then(async (reply) => {
      if (!reply.ok) throw new Error(`source kind ${kind}: ${reply.status}`);
      return (await reply.json()) as SourceKind;
    });
    // A failed ask is asked again next time, not remembered.
    answer.catch(() => asked.delete(kind));
    asked.set(kind, answer);
  }
  return answer;
}

/** The kind's facts, or null until the server has said them (and when it could not be asked:
 * the server states each rule again when the source is saved). */
export function useSourceKind(kind: string): SourceKind | null {
  const [known, setKnown] = useState<{ kind: string; said: SourceKind } | null>(null);
  useEffect(() => {
    if (!kind) return;
    let current = true;
    sourceKind(kind).then(
      (said) => current && setKnown({ kind, said }),
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [kind]);
  return known !== null && known.kind === kind ? known.said : null;
}

/** Whether a source of `kind` must state its Cache TTL. False until the server has said so: the
 * server refuses the save by name either way (schema.source_cache_ttl_required). */
export function useCacheTtlRequired(kind: string): boolean {
  return useSourceKind(kind)?.cache_ttl_required === true;
}
