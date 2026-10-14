// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * A node's stable id, the number the Inspector shows: one per node identity (its label and primary
 * key), kept in this browser's storage. Apart from graph-model, which the server-side renderer
 * (graph-render) bundles for Node, where there is no browser storage.
 */
import { getStored, setStored } from "../../lib/browserStorage";

// ── Stable node ID ────────────────────────────────────────────────────────────
const LS_IDS = "provisa_stable_node_ids";
const LS_CTR = "provisa_stable_node_id_counter";

function _stableKey(
  node: { label: string; properties: Record<string, unknown> },
  pkMap: Record<string, string[]>,
): string {
  const pkCols = pkMap[node.label] ?? [];
  if (pkCols.length > 0) {
    const pkVal = pkCols.map((c) => String(node.properties[c] ?? "")).join(":");
    return `${node.label}::${pkVal}`;
  }
  // Fallback: hash all property values deterministically
  const sorted = Object.keys(node.properties)
    .sort()
    .map((k) => `${k}=${String(node.properties[k])}`)
    .join("|");
  return `${node.label}::${sorted}`;
}

export function getStableNodeId(
  node: { label: string; properties: Record<string, unknown> },
  pkMap: Record<string, string[]>,
): number {
  const key = _stableKey(node, pkMap);
  let map: Record<string, number> = {};
  try {
    map = JSON.parse(getStored(LS_IDS) ?? "{}");
  } catch {
    /* */
  }
  if (key in map) return map[key];
  let ctr = 0;
  try {
    ctr = parseInt(getStored(LS_CTR) ?? "0", 10) || 0;
  } catch {
    /* */
  }
  ctr += 1;
  map[key] = ctr;
  try {
    setStored(LS_IDS, JSON.stringify(map));
    setStored(LS_CTR, String(ctr));
  } catch {
    /* */
  }
  return ctr;
}
