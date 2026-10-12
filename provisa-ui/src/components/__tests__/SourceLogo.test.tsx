// Copyright (c) 2026 Kenneth Stott
// Canary: 1a86ecf7-127e-4353-ab6a-089b0a19ddfd
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A source type's logo in the picker: its own mark where one may be shown, from simple-icons or a
// bundled file, and a lettered tile in its category's colour otherwise.

import { describe, expect, it } from "vitest";
import { render, screen } from "../../test-utils/render";
import { SourceLogo } from "../SourceLogo";

const logo = (type: string, label: string, category: string) => {
  render(<SourceLogo type={type} label={label} category={category} />);
  return screen.getByTestId(`source-logo-${type}`);
};

describe("a source type's logo", () => {
  it("is AskAmerica's own mark, from the bundled file, not a tile", () => {
    const el = logo("govdata", "AskAmerica (US Government Data)", "Subscriptions");
    expect(el.tagName).toBe("IMG");
    expect(el).toHaveAttribute("data-logo", "file");
    expect(el.getAttribute("src")).toMatch(/askamerica\.svg|^data:image\/svg\+xml/);
    expect(el).not.toHaveTextContent("AS");
  });

  it("is the simple-icons mark for a type that has one", () => {
    expect(logo("postgresql", "PostgreSQL", "RDBMS")).toHaveAttribute("data-logo", "mark");
  });

  it("is a lettered tile for a type with no mark that may be shown", () => {
    const el = logo("oracle", "Oracle", "RDBMS");
    expect(el).toHaveAttribute("data-logo", "tile");
    expect(el).toHaveTextContent("OR");
  });
});
