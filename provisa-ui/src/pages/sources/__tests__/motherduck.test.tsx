// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1

// REQ-1998: a MotherDuck source is in the pick list under the cloud warehouses; its form names
// the database (or share) and the token, and says that a join with a local DuckDB file may send
// the file's rows to the MotherDuck account.

import { useState } from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, renderInForm, screen } from "../../../test-utils/render";
import { MotherDuckFields } from "../MotherDuckFields";
import { SOURCE_TYPES } from "../constants";
import type { SourceFormState } from "../SourceFormFields";

const START = { id: "md", type: "motherduck", database: "", password: "" } as SourceFormState;

function Harness({ onForm }: { onForm: (form: SourceFormState) => void }) {
  const [form, setForm] = useState(START);
  return (
    <MotherDuckFields
      form={form}
      setForm={(next) => {
        onForm(next);
        setForm(next);
      }}
    />
  );
}

describe("MotherDuck", () => {
  it("is offered with the cloud warehouses", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "motherduck")).toMatchObject({
      label: "MotherDuck",
      category: "Cloud DW",
    });
  });

  it("names the database and the token, and says where a hybrid join's rows may go", () => {
    let last: SourceFormState = START;
    renderInForm(<Harness onForm={(f) => (last = f)} />);
    fireEvent.change(screen.getByTestId("motherduck-database"), { target: { value: "my_db" } });
    fireEvent.change(screen.getByTestId("motherduck-token"), {
      target: { value: "${secret:md}" },
    });
    expect(last).toMatchObject({ database: "my_db", password: "${secret:md}" });
    expect(screen.getByTestId("motherduck-data-movement")).toHaveTextContent(
      /may send the file's rows to your MotherDuck account/,
    );
  });
});
