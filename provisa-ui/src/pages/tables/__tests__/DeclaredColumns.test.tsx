// Copyright (c) 2026 Kenneth Stott
// Canary: 26e8e860-cc46-4f99-9ac1-df7da7b51e7b
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1924: the steward declares the columns of an OpenAPI table whose operation declares no
// response schema; a sample answer only suggests.

import { useEffect, useState } from "react";
import { describe, expect, it } from "vitest";
import { MockedProvider } from "@apollo/client/testing/react";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderInForm, screen } from "../../../test-utils/render";
import { SampleOpenapiColumns } from "../../../hooks/admin.graphql";
import { DeclaredColumns } from "../DeclaredColumns";
import { blankColumn, type ColumnForm } from "../types";

const site: ColumnForm = {
  ...blankColumn("_nf_site", "text", ["admin"]),
  nativeFilterType: "path_param",
  nativeFilterRequired: true,
};

const seen: { columns: ColumnForm[] } = { columns: [] };
const report = (columns: ColumnForm[]) => {
  seen.columns = columns;
};

function Harness({ start }: { start: ColumnForm[] }) {
  const [columns, setColumns] = useState(start);
  useEffect(() => report(columns), [columns]);
  return (
    <DeclaredColumns
      sourceId="shelter"
      tableName="listDogs"
      columns={columns}
      setColumns={setColumns}
      irTypes={["text", "bigint", "boolean"]}
      visibleTo={["admin"]}
    />
  );
}

const sampled = {
  request: {
    query: SampleOpenapiColumns,
    variables: { sourceId: "shelter", tableName: "listDogs", params: { site: "north" } },
  },
  result: {
    data: {
      sampleOpenapiColumns: [
        { __typename: "AvailableColumnType", name: "name", dataType: "text" },
        { __typename: "AvailableColumnType", name: "age", dataType: "bigint" },
      ],
    },
  },
};

describe("DeclaredColumns", () => {
  it("adds, renames and removes a declared column, leaving the parameter as it is", () => {
    renderInForm(
      <MockedProvider mocks={[]}>
        <Harness start={[site]} />
      </MockedProvider>,
    );
    fireEvent.click(screen.getByTestId("declared-column-add"));
    fireEvent.change(screen.getByTestId("declared-column-name-1"), {
      target: { value: "name" },
    });
    expect(seen.columns.map((c) => [c.name, c.dataType, c.nativeFilterType])).toEqual([
      ["_nf_site", "text", "path_param"],
      ["name", "text", null],
    ]);
    fireEvent.click(screen.getByTestId("declared-column-remove-1"));
    expect(seen.columns.map((c) => c.name)).toEqual(["_nf_site"]);
  });

  it("a sample called with the parameter values only suggests columns, each editable", async () => {
    renderInForm(
      <MockedProvider mocks={[sampled]}>
        <Harness start={[site, blankColumn("name", "text", ["admin"])]} />
      </MockedProvider>,
    );
    fireEvent.change(screen.getByTestId("declared-sample-param-site"), {
      target: { value: "north" },
    });
    fireEvent.click(screen.getByTestId("declared-sample"));
    // "name" is declared already; only "age" is added.
    await waitFor(() =>
      expect(seen.columns.map((c) => c.name)).toEqual(["_nf_site", "name", "age"]),
    );
    expect(seen.columns[2].dataType).toBe("bigint");
    expect(screen.getByTestId("declared-column-name-2")).toHaveValue("age");
  });
});
