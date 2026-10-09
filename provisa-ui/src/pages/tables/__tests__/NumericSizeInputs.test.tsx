// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.

// REQ-1961: a numeric column's precision and scale are set beside its type. Both set, the type
// is the one stored spelling `numeric(p,s)`; both empty, it is a bare `numeric`.

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "../../../test-utils/render";
import { NumericSizeInputs } from "../NumericSizeInputs";
import { isNumericSize, numericSize, numericType } from "../../../irTypes";

const precision = () => screen.getByRole("textbox", { name: "Precision" });
const scale = () => screen.getByRole("textbox", { name: "Scale" });

describe("numeric size helpers (REQ-1961)", () => {
  it("reads the size a type declares", () => {
    expect(numericSize("numeric(18,2)")).toEqual({ precision: 18, scale: 2 });
    expect(numericSize("DECIMAL(10, 4)")).toEqual({ precision: 10, scale: 4 });
    expect(numericSize("decimal(9)")).toEqual({ precision: 9, scale: 0 });
    expect(numericSize("numeric")).toBeNull();
    expect(numericSize("varchar(40)")).toBeNull();
  });

  it("writes the one stored spelling", () => {
    expect(numericType({ precision: 18, scale: 2 })).toBe("numeric(18,2)");
    expect(numericType(null)).toBe("numeric");
  });

  it("knows which sizes a numeric can have", () => {
    expect(isNumericSize(18, 2)).toBe(true);
    expect(isNumericSize(76, 76)).toBe(true);
    expect(isNumericSize(5, 9)).toBe(false);
    expect(isNumericSize(0, 0)).toBe(false);
    expect(isNumericSize(77, 2)).toBe(false);
  });
});

describe("NumericSizeInputs (REQ-1961)", () => {
  it("shows the size the column declares and says it is exact", () => {
    render(<NumericSizeInputs dataType="numeric(18,2)" onChange={vi.fn()} />);
    expect(precision()).toHaveValue("18");
    expect(scale()).toHaveValue("2");
    expect(screen.getByText("Exact: read with these digits")).toBeInTheDocument();
  });

  it("says a numeric with no size is read as an approximate number", () => {
    render(<NumericSizeInputs dataType="numeric" onChange={vi.fn()} />);
    expect(precision()).toHaveValue("");
    expect(scale()).toHaveValue("");
    expect(screen.getByText("No size: read as an approximate number")).toBeInTheDocument();
  });

  it("changes the type only once both fields size a numeric", () => {
    const onChange = vi.fn();
    render(<NumericSizeInputs dataType="numeric" onChange={onChange} />);
    fireEvent.change(precision(), { target: { value: "12" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(scale(), { target: { value: "4" } });
    expect(onChange).toHaveBeenLastCalledWith("numeric(12,4)");
  });

  it("refuses a scale greater than the precision without changing the type", () => {
    const onChange = vi.fn();
    render(<NumericSizeInputs dataType="numeric(5,2)" onChange={onChange} />);
    fireEvent.change(scale(), { target: { value: "9" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(
      screen.getByText("Precision is 1 to 76; scale is 0 to the precision"),
    ).toBeInTheDocument();
  });

  it("clearing both fields makes the column a bare numeric", () => {
    const onChange = vi.fn();
    render(<NumericSizeInputs dataType="numeric(5,2)" onChange={onChange} />);
    fireEvent.change(precision(), { target: { value: "" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(scale(), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("numeric");
  });
});
