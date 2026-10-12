// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1983: a Qdrant source is its URL and API key, read over REST or gRPC.

import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, renderInForm, screen } from "../../../test-utils/render";
import { QdrantFields } from "../QdrantFields";
import { SOURCE_TYPES } from "../constants";
import {
  offeredUnselected,
  qdrantFieldsFromHints,
  qdrantHints,
  searchQueryArgument,
} from "../qdrant";
import type { SourceFormState } from "../SourceFormFields";

describe("the source pick list", () => {
  it("offers Qdrant among the NoSQL sources", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "qdrant")).toMatchObject({
      label: "Qdrant",
      category: "NoSQL",
    });
  });
});

describe("what a Qdrant source saves", () => {
  it("is whether it reads over gRPC, and back", () => {
    expect(qdrantHints({})).toEqual({ prefer_grpc: false });
    expect(qdrantFieldsFromHints(JSON.stringify(qdrantHints({ qdrant_grpc: "true" })))).toEqual({
      qdrant_grpc: "true",
    });
  });
});

describe("a search and a collection's columns", () => {
  it("names the argument its query is", () => {
    expect(searchQueryArgument('{"collection": "docs", "query": "@q"}')).toBe("q");
    expect(searchQueryArgument('{"collection": "docs", "query": [0.1]}')).toBeNull();
    expect(searchQueryArgument("{not json")).toBeNull();
  });

  it("offers a collection's vectors unselected", () => {
    expect(offeredUnselected("qdrant", "@vector")).toBe(true);
    expect(offeredUnselected("qdrant", "@vector.image")).toBe(true);
    expect(offeredUnselected("qdrant", "title")).toBe(false);
    expect(offeredUnselected("mongodb", "@vector")).toBe(false);
  });
});

function Harness({ onForm }: { onForm: (f: SourceFormState) => void }) {
  const [form, setForm] = useState({ host: "", password: "" } as SourceFormState);
  const [fields, setFields] = useState<Record<string, string>>({});
  return (
    <QdrantFields
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

describe("the Qdrant fields", () => {
  it("ask the URL and the API key", () => {
    const onForm = vi.fn();
    renderInForm(<Harness onForm={onForm} />);
    fireEvent.change(screen.getByTestId("qdrant-url"), {
      target: { value: "https://q.example.com:6333" },
    });
    fireEvent.change(screen.getByTestId("qdrant-api-key"), {
      target: { value: "${secret:QDRANT_KEY}" },
    });
    expect(onForm.mock.lastCall?.[0]).toMatchObject({
      host: "https://q.example.com:6333",
      password: "${secret:QDRANT_KEY}",
    });
  });
});
