// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1981: Amazon Athena is in the source pick list under Cloud DW; its form asks for its region
// and database, where Athena writes results, a key pair (or none) and an optional role.

import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderInForm, screen } from "../../../test-utils/render";
import { AthenaFields } from "../AthenaFields";
import { SOURCE_TYPES } from "../constants";
import { athenaHints, athenaResultLocationValid } from "../athena";

const FORM = { database: "sales", username: "", password: "" };

describe("the source pick list", () => {
  it("offers Amazon Athena under Cloud DW", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "athena")).toMatchObject({
      label: "Amazon Athena",
      category: "Cloud DW",
    });
  });
});

describe("athenaHints", () => {
  it("saves each setting given, trimmed, and nothing else", () => {
    expect(
      athenaHints({
        region: " us-east-1 ",
        workgroup: "",
        s3_staging_dir: "s3://b/results/",
        role_arn: "arn:aws:iam::1:role/r",
        stray: "x",
      }),
    ).toEqual({
      region: "us-east-1",
      s3_staging_dir: "s3://b/results/",
      role_arn: "arn:aws:iam::1:role/r",
    });
  });

  it("takes an s3:// result location, a reference, or none", () => {
    expect(athenaResultLocationValid("s3://bucket/results/")).toBe(true);
    expect(athenaResultLocationValid("${secret:athena_results}")).toBe(true);
    expect(athenaResultLocationValid("")).toBe(true);
    expect(athenaResultLocationValid("https://bucket/results/")).toBe(false);
  });
});

describe("AthenaFields", () => {
  it("asks for the region and database, and the secret only once a key ID is given", () => {
    const setFields = vi.fn();
    const { rerender } = renderInForm(
      <AthenaFields form={FORM} setForm={vi.fn()} fields={{}} setFields={setFields} />,
    );
    expect(screen.getByTestId("athena-region-input")).toBeRequired();
    expect(screen.getByTestId("athena-database-input")).toHaveValue("sales");
    expect(screen.getByTestId("athena-secret-key-input")).not.toBeRequired();
    fireEvent.change(screen.getByTestId("athena-region-input"), {
      target: { value: "us-east-1" },
    });
    expect(setFields).toHaveBeenLastCalledWith({ region: "us-east-1" });
    rerender(
      <AthenaFields
        form={{ ...FORM, username: "AKIA" }}
        setForm={vi.fn()}
        fields={{}}
        setFields={setFields}
      />,
    );
    expect(screen.getByTestId("athena-secret-key-input")).toBeRequired();
  });

  it("says a result location that is not s3:// is not one Athena takes", () => {
    renderInForm(
      <AthenaFields
        form={FORM}
        setForm={vi.fn()}
        fields={{ s3_staging_dir: "https://x/" }}
        setFields={vi.fn()}
      />,
    );
    expect(screen.getByText(/Enter an s3:\/\/ location/)).toBeInTheDocument();
  });
});
