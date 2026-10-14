// Copyright (c) 2026 Kenneth Stott
// Canary: 1e1692c9-fcee-4515-b4cb-b863c3bf6b7a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useCallback, useRef } from "react";
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
 *
 * A call made while a read is in flight shares it: a lazy query's execute aborts the call still in
 * flight when it runs again, and two quick starts of the tour (`?tour=1`) left the first rejected
 * with "The operation was aborted" and the tour not started.
 */
export function useOrgHas(): () => Promise<OrgHas> {
  const [loadSources] = useLazyQuery<{ sources: Source[] }>(SOURCES_QUERY);
  const [loadTables] = useLazyQuery<{ tables: RegisteredTable[] }>(TABLES_QUERY);
  const [loadProducts] = useLazyQuery<{ dataProducts: DataProduct[] }>(DATA_PRODUCTS_QUERY);
  const inFlight = useRef<Promise<OrgHas> | null>(null);
  const read = useCallback(async (): Promise<OrgHas> => {
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
  return useCallback(() => {
    if (inFlight.current === null) {
      inFlight.current = read().finally(() => {
        inFlight.current = null;
      });
    }
    return inFlight.current;
  }, [read]);
}
