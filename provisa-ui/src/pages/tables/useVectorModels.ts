// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useQuery } from "@apollo/client/react";
import { QdrantVectors } from "../../hooks/admin.graphql";

const VECTOR_PATH = "@vector";

interface QdrantVector {
  name: string;
  size: number;
  distance: string;
  models: string[];
}

/** The vector a column reads ("" for the collection's unnamed one), or null for any other column. */
export function vectorOf(path: string | null | undefined): string | null {
  if (path === VECTOR_PATH) return "";
  return path?.startsWith(VECTOR_PATH + ".") ? path.slice(VECTOR_PATH.length + 1) : null;
}

/** Each vector of a Qdrant collection with the registered models its column may name, by vector
 * name; empty until a collection is named. */
export function useVectorModels(
  sourceId: string,
  collection: string,
  enabled: boolean,
): Record<string, string[]> {
  const { data } = useQuery<{ qdrantVectors: QdrantVector[] }>(QdrantVectors, {
    variables: { sourceId, collection },
    skip: !enabled || !sourceId || !collection,
  });
  return Object.fromEntries((data?.qdrantVectors ?? []).map((v) => [v.name, v.models]));
}
