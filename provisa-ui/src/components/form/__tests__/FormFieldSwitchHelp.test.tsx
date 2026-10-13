// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A file of its own: React reports an unknown DOM attribute once per process, so a warning raised
// by an earlier test in a shared file would hide this one.

import { describe, it, expect, vi } from "vitest";
import { Switch } from "@mantine/core";
import { render } from "../../../test-utils/render";
import { FormField, FormLayout } from "../FormLayout";

describe("a field's help on a switch", () => {
  it("gives the switch no prop its element does not take", () => {
    // A Switch has no asterisk to drop: handed `withAsterisk`, it set it on its <input>, and React
    // warned of an unknown attribute -- an uncaught browser error to the e2e suite (a fake's
    // "stable" switch, on the Test data deep dive's path).
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <FormLayout>
        <FormField size="short" help="The same fake every run.">
          <Switch label="Stable" />
        </FormField>
      </FormLayout>,
    );
    const warned = spy.mock.calls.map((c) => c.join(" ")).filter((m) => /withAsterisk/i.test(m));
    spy.mockRestore();
    expect(warned).toEqual([]);
  });
});
