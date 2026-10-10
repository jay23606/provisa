// What the server says of a source kind before anything is saved (/admin/source-kinds/{kind}).
// One fact: whether a source of the kind must state its Cache TTL itself -- every table of it
// lands and refreshes by that one clock (REQ-1907). The rule is the server's; the form asks.

import { useEffect, useState } from "react";

export interface SourceKind {
  cache_ttl_required: boolean;
}

const asked = new Map<string, Promise<SourceKind>>();

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

/** Whether a source of `kind` must state its Cache TTL. False until the server has said so: the
 * server refuses the save by name either way (schema.source_cache_ttl_required). */
export function useCacheTtlRequired(kind: string): boolean {
  const [known, setKnown] = useState<{ kind: string; required: boolean } | null>(null);
  useEffect(() => {
    if (!kind) return;
    let current = true;
    sourceKind(kind).then(
      (said) => current && setKnown({ kind, required: said.cache_ttl_required }),
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [kind]);
  return known !== null && known.kind === kind && known.required;
}
