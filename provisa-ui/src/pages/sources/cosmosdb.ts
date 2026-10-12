// Copyright (c) 2026 Kenneth Stott
// Canary: a64e6e31-fd05-4cdf-8395-4b2da9ae8ad9
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1982: an Azure Cosmos DB for NoSQL source signs in with its account key, or as a Microsoft
// Entra service principal. The endpoint is the source's host and the database its database; the
// key, or the principal's client secret, is its password. How it signs in, and the principal's
// tenant and client, ride in its federation hints (provisa/cosmosdb/fetch.py).

export const COSMOSDB = "cosmosdb";
export const COSMOS_KEY = "key";
export const COSMOS_ENTRA = "entra";

/** The source's federation hints for what the fields say. */
export function cosmosHints(fields: Record<string, string>): Record<string, string> {
  if ((fields.cosmos_auth ?? COSMOS_KEY) !== COSMOS_ENTRA) return { auth: COSMOS_KEY };
  return {
    auth: COSMOS_ENTRA,
    tenant_id: (fields.cosmos_tenant_id ?? "").trim(),
    client_id: (fields.cosmos_client_id ?? "").trim(),
  };
}

/** The fields an existing source's hints fill in. */
export function cosmosFieldsFromHints(
  hintsJson: string | null | undefined,
): Record<string, string> {
  const hints = hintsJson ? (JSON.parse(hintsJson) as Record<string, string>) : {};
  return {
    cosmos_auth: hints.auth ?? COSMOS_KEY,
    cosmos_tenant_id: hints.tenant_id ?? "",
    cosmos_client_id: hints.client_id ?? "",
  };
}
