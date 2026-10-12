// Copyright (c) 2026 Kenneth Stott
// Canary: 46d8ab90-e1db-45dc-b86d-896874df68b6
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-855, REQ-982: a mail source whose provider can be asked whether the mailbox changed
// offers two choices, in words: re-read on the schedule, or check first and re-read only when
// something changed. A source with no such probe keeps the form's ordinary list.

import { useState } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderInForm, screen, within } from "../../../test-utils/render";
import { SourceLoadManagementPanel } from "../SourceLoadManagementPanel";
import type { SourceFormState } from "../SourceFormFields";
import en from "../../../i18n/locales/en/sourceFormFieldsExtended.json";

const WORDS = en.sourceFormFieldsExtended.sourceProbeSignal;

function Harness({ type, seen }: { type: string; seen: (f: SourceFormState) => void }) {
  const [form, setForm] = useState({
    id: "mail",
    type,
    cacheTtl: "300",
    cacheEnabled: true,
    replicate: null,
    loadProtected: false,
    offPeakWindow: "",
    offPeakTz: "UTC",
    changeSignal: "ttl",
    sentinelPath: "",
    freshnessGate: false,
    maxLiveConcurrency: "",
  } as unknown as SourceFormState);
  return (
    <SourceLoadManagementPanel
      form={form}
      setForm={(f) => {
        setForm(f);
        seen(f);
      }}
    />
  );
}

async function openChoices(type: string, seen: (f: SourceFormState) => void = () => undefined) {
  renderInForm(<Harness type={type} seen={seen} />);
  const input = await screen.findByTestId("change-signal-select");
  await userEvent.click(input);
  // Mantine keeps a drop-down out of the accessibility tree in jsdom: reach this one through
  // the input's aria-controls listbox.
  const listbox = document.getElementById(input.getAttribute("aria-controls") as string);
  if (listbox === null) throw new Error("the change-signal drop-down did not open");
  return within(listbox).getAllByRole("option", { hidden: true });
}

const words = (options: HTMLElement[]) => options.map((option) => option.textContent);

describe("a mail source's change signal", () => {
  it("offers Google Workspace the schedule, or checking first, in words", async () => {
    const chosen: SourceFormState[] = [];
    const offered = await openChoices("google_workspace", (f) => chosen.push(f));
    expect(words(offered)).toEqual([WORDS.ttl, WORDS.ttl_probe]);
    await userEvent.click(offered[1]);
    expect(chosen.at(-1)?.changeSignal).toBe("ttl_probe");
  });

  it("offers Microsoft 365 the same two choices", async () => {
    expect(words(await openChoices("microsoft_365"))).toEqual([WORDS.ttl, WORDS.ttl_probe]);
  });

  it("leaves every other source's list as it was", async () => {
    expect(words(await openChoices("postgresql"))).toEqual([
      "ttl (timer)",
      "native (source push)",
      "debezium",
      "kafka",
    ]);
  });
});
