// Copyright (c) 2026 Kenneth Stott
// Canary: 8e6f5775-24a0-49a4-8e60-66ac1f15139a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1982: an Azure Cosmos DB for NoSQL source is its account endpoint and database, signed in
// with the account key or as a Microsoft Entra service principal.

import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, renderInForm, screen } from "../../../test-utils/render";
import { CosmosDbFields } from "../CosmosDbFields";
import { SOURCE_TYPES } from "../constants";
import { cosmosFieldsFromHints, cosmosHints } from "../cosmosdb";
import type { SourceFormState } from "../SourceFormFields";

describe("the source pick list", () => {
  it("offers Azure Cosmos DB among the NoSQL sources", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "cosmosdb")).toMatchObject({
      label: "Azure Cosmos DB",
      category: "NoSQL",
    });
  });
});

describe("what a Cosmos DB source saves", () => {
  it("is the account key by default, and nothing else in its hints", () => {
    expect(cosmosHints({})).toEqual({ auth: "key" });
  });

  it("is the service principal's tenant and client when it signs in with Entra", () => {
    const fields = { cosmos_auth: "entra", cosmos_tenant_id: " t1 ", cosmos_client_id: "c1" };
    expect(cosmosHints(fields)).toEqual({ auth: "entra", tenant_id: "t1", client_id: "c1" });
    expect(cosmosFieldsFromHints(JSON.stringify(cosmosHints(fields)))).toEqual({
      cosmos_auth: "entra",
      cosmos_tenant_id: "t1",
      cosmos_client_id: "c1",
    });
  });
});

function Harness({ onForm }: { onForm: (f: SourceFormState) => void }) {
  const [form, setForm] = useState({ host: "", database: "", password: "" } as SourceFormState);
  const [fields, setFields] = useState<Record<string, string>>({});
  return (
    <CosmosDbFields
      form={form}
      setForm={(f) => {
        onForm(f);
        setForm(f);
      }}
      fields={fields}
      setFields={setFields}
    />
  );
}

describe("the Cosmos DB fields", () => {
  it("ask the endpoint, the database and the account key, and the principal only for Entra", () => {
    const onForm = vi.fn();
    renderInForm(<Harness onForm={onForm} />);
    fireEvent.change(screen.getByTestId("cosmosdb-endpoint"), {
      target: { value: "https://acct.documents.azure.com:443/" },
    });
    fireEvent.change(screen.getByTestId("cosmosdb-database"), { target: { value: "shop" } });
    fireEvent.change(screen.getByTestId("cosmosdb-secret"), { target: { value: "${env:KEY}" } });
    expect(onForm.mock.lastCall?.[0]).toMatchObject({
      host: "https://acct.documents.azure.com:443/",
      database: "shop",
      password: "${env:KEY}",
    });
    expect(screen.queryByTestId("cosmosdb-tenant-id")).toBeNull();
  });
});
