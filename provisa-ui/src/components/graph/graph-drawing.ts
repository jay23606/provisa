// Copyright (c) 2026 Kenneth Stott
// Canary: 2c9e6b41-7d3a-4f58-b1e0-9a4d5c7f8e26
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// What the explorer draws of a Cypher result that returns nodes, relationships or paths: its rows,
// in order, up to "max nodes" distinct nodes (a node repeated across rows counts once). The rows
// are what the server returned under its row limits; a result whose rows hold fewer nodes is drawn
// whole. Max nodes is the viewer's own setting, saved per scope. A result that returns rows only
// is not drawn.

import { useCallback, useState } from "react";
import { getStored, setStored } from "../../lib/browserStorage";
import { extractElements, type GEdge, type GNode } from "./graph-model";

export const MAX_NODES_KEY = "provisa.graph.max_nodes";
export const DEFAULT_MAX_NODES = 300;

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

/** The nodes and relationships of a /data/cypher answer to draw: those of its rows, in order, up
 *  to `maxNodes` distinct nodes, when the server says a column is drawn (graph_columns, from the
 *  translation); and whether a row was left out because its nodes would have passed `maxNodes`. */
export function drawnElements(
  data: { rows?: Record<string, unknown>[]; graph_columns?: Record<string, string> },
  maxNodes: number,
): { nodes: Map<string, GNode>; edges: Map<string, GEdge>; truncated: boolean } {
  const nodes = new Map<string, GNode>();
  const edges = new Map<string, GEdge>();
  if (Object.keys(data.graph_columns ?? {}).length === 0) return { nodes, edges, truncated: false };
  for (const row of data.rows ?? []) {
    const found = extractElements([row]);
    const fresh = [...found.nodes.keys()].filter((k) => !nodes.has(k)).length;
    if (nodes.size + fresh > maxNodes) return { nodes, edges, truncated: true };
    found.nodes.forEach((node, k) => nodes.set(k, node));
    found.edges.forEach((edge, k) => edges.set(k, edge));
  }
  return { nodes, edges, truncated: false };
}
