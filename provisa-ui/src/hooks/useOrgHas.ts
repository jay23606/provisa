// Copyright (c) 2026 Kenneth Stott
// Canary: 1e1692c9-fcee-4515-b4cb-b863c3bf6b7a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useCallback } from "react";
import { useLazyQuery } from "@apollo/client/react";
import type { DataProduct, RegisteredTable, Source } from "../types/admin";
import type { OrgHas } from "../tour/tourPrerequisites";
import {
  DataProductsQuery as DATA_PRODUCTS_QUERY,
  SourcesQuery as SOURCES_QUERY,
  TablesQuery as TABLES_QUERY,
} from "./admin.graphql";

/**
 * REQ-2013: a function reading what the current org has that a tour's steps may need -- its
 * sources, its registered tables (`<source>.<table>`) and how many data products -- from the
 * cached catalog, else the server. A read that fails rejects; it is never taken for "none".
 */
export function useOrgHas(): () => Promise<OrgHas> {
  const [loadSources] = useLazyQuery<{ sources: Source[] }>(SOURCES_QUERY);
  const [loadTables] = useLazyQuery<{ tables: RegisteredTable[] }>(TABLES_QUERY);
  const [loadProducts] = useLazyQuery<{ dataProducts: DataProduct[] }>(DATA_PRODUCTS_QUERY);
  return useCallback(async () => {
    const [sources, tables, products] = await Promise.all([
      loadSources(),
      loadTables(),
      loadProducts(),
    ]);
    if (!sources.data || !tables.data || !products.data) {
      throw new Error("Tour: the org's sources, tables or data products could not be read");
    }
    return {
      sources: new Set(sources.data.sources.map((x) => x.id)),
      tables: new Set(tables.data.tables.map((x) => `${x.sourceId}.${x.tableName}`)),
      dataProducts: products.data.dataProducts.length,
    };
  }, [loadSources, loadTables, loadProducts]);
}
