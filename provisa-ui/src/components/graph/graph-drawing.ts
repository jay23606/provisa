// Copyright (c) 2026 Kenneth Stott
// Canary: 2c9e6b41-7d3a-4f58-b1e0-9a4d5c7f8e26
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// What the explorer draws of a Cypher result: the first "max nodes" rows of one that returns
// nodes, relationships or paths. Max nodes is the viewer's own setting, saved per scope, and is
// held to the server's drawing ceiling (graph-schema's node_cap: the smaller of the row limit and
// the large-result redirect threshold), which the server holds it to. A result that returns rows only is not drawn or capped.

import { useCallback, useState } from "react";
import { getStored, setStored } from "../../lib/browserStorage";
import { extractElements, type GEdge, type GNode } from "./graph-model";

export const MAX_NODES_KEY = "provisa.graph.max_nodes";
export const DEFAULT_MAX_NODES = 1000;

function readMaxNodes(): number {
  const stored = Number(getStored(MAX_NODES_KEY));
  return Number.isInteger(stored) && stored > 0 ? stored : DEFAULT_MAX_NODES;
}

/** The viewer's max-nodes setting and its setter, which saves it. */
export function useMaxNodes(): [number, (n: number) => void] {
  const [maxNodes, setMaxNodes] = useState(readMaxNodes);
  const save = useCallback((n: number) => {
    setStored(MAX_NODES_KEY, String(n));
    setMaxNodes(n);
  }, []);
  return [maxNodes, save];
}

/** The nodes and relationships of a /data/cypher answer, from the columns the server says it
 *  draws (graph_columns, from the translation), and whether it was cut at max nodes. */
export function drawnElements(data: {
  rows?: Record<string, unknown>[];
  graph_columns?: Record<string, string>;
  truncated?: boolean;
}): { nodes: Map<string, GNode>; edges: Map<string, GEdge>; truncated: boolean } {
  if (Object.keys(data.graph_columns ?? {}).length === 0)
    return { nodes: new Map(), edges: new Map(), truncated: false };
  return { ...extractElements(data.rows ?? []), truncated: data.truncated === true };
}
