// Copyright (c) 2026 Kenneth Stott
// Canary: 5b330d17-eae2-4cb3-bdc3-8eb4aee64c7a
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { describe, it, expect, vi } from "vitest";
import { Button, Checkbox, TextInput } from "@mantine/core";
import { render, screen } from "../../../test-utils/render";
import i18n from "../../../i18n";
import {
  FieldGroup,
  FormChecks,
  FormField,
  FormFooter,
  FormIdentifiers,
  FormLayout,
} from "../FormLayout";

const t = i18n.getFixedT("en");

// REQ-1968: one shared form layout; identifiers in a section of their own above the flow.
describe("FormLayout", () => {
  it("renders a field in its size class", () => {
    render(
      <FormLayout>
        <FormField size="short" data-testid="port-field">
          <TextInput label="Port" />
        </FormField>
      </FormLayout>,
    );
    expect(screen.getByTestId("port-field")).toHaveClass("form-field", "form-field--short");
    expect(screen.getByLabelText("Port")).toBeInTheDocument();
  });

  it("renders as a form and submits", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <FormLayout component="form" onSubmit={onSubmit} data-testid="the-form">
        <button type="submit">go</button>
      </FormLayout>,
    );
    const form = screen.getByTestId("the-form");
    expect(form.tagName).toBe("FORM");
    expect(form).toHaveClass("form-layout");
    screen.getByRole("button", { name: "go" }).click();
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("puts identifiers in a headed section before the flow", () => {
    render(
      <FormLayout data-testid="layout">
        <FormIdentifiers>
          <FormField size="medium">
            <TextInput label="Source ID" />
          </FormField>
        </FormIdentifiers>
        <FormField size="long">
          <TextInput label="Description" />
        </FormField>
      </FormLayout>,
    );
    const section = screen.getByRole("region", { name: t("common.identity") });
    expect(section).toContainElement(screen.getByLabelText("Source ID"));
    expect(section).not.toContainElement(screen.getByLabelText("Description"));
    expect(screen.getByTestId("layout").firstElementChild).toBe(section);
  });

  it("keeps grouped fields in one wrapping unit, in reading order", () => {
    render(
      <FormLayout>
        <FieldGroup data-testid="host-port">
          <FormField size="medium">
            <TextInput label="Host" />
          </FormField>
          <FormField size="short">
            <TextInput label="Port" />
          </FormField>
        </FieldGroup>
      </FormLayout>,
    );
    const group = screen.getByTestId("host-port");
    expect(group).toHaveClass("form-field-group");
    const inputs = Array.from(group.querySelectorAll("input"));
    expect(inputs).toEqual([screen.getByLabelText("Host"), screen.getByLabelText("Port")]);
  });

  it("gives a list entry a line to itself", () => {
    render(
      <FormLayout>
        <FieldGroup row data-testid="entry">
          <FormField size="medium">
            <TextInput label="Role" />
          </FormField>
        </FieldGroup>
      </FormLayout>,
    );
    expect(screen.getByTestId("entry")).toHaveClass("form-field-group", "form-field-group--row");
  });

  it("puts a brief explanation below the control, and nothing between label and control", () => {
    render(
      <FormLayout>
        <FormField size="medium" hint="The mailbox this source reads.">
          <TextInput label="Mailbox address" />
        </FormField>
      </FormLayout>,
    );
    const input = screen.getByLabelText("Mailbox address");
    const hint = screen.getByText("The mailbox this source reads.");
    expect(input.compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input).toHaveAccessibleDescription("The mailbox this source reads.");
  });

  it("keeps an explanation a form passes straight to a control below it too", () => {
    render(<TextInput label="Host" description="Where it is." />);
    const input = screen.getByLabelText("Host");
    const text = screen.getByText("Where it is.");
    expect(input.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("puts a longer explanation behind a (?) right after the label", () => {
    render(
      <FormLayout>
        <FormField size="medium" help="One mailbox is connected by its owner.">
          <TextInput label="Whose mail" />
        </FormField>
      </FormLayout>,
    );
    const input = screen.getByLabelText("Whose mail");
    const icon = screen.getByRole("img", { name: "One mailbox is connected by its owner." });
    expect(icon.closest("label")).toBe(
      input.closest(".mantine-InputWrapper-root")?.querySelector("label"),
    );
    expect(icon).toHaveAttribute("tabindex", "0");
    expect(screen.queryByText("One mailbox is connected by its owner.")).not.toBeInTheDocument();
  });

  it("keeps the ticks of a form together, each with its optional (?)", () => {
    render(
      <FormLayout>
        <FormChecks data-testid="ticks">
          <Checkbox label="Cache enabled" />
          <FormField size="short" help="Serve only what is fresh.">
            <Checkbox label="Freshness gate" />
          </FormField>
        </FormChecks>
      </FormLayout>,
    );
    const ticks = screen.getByTestId("ticks");
    expect(ticks).toHaveClass("form-checks");
    expect(ticks).toContainElement(screen.getByLabelText("Cache enabled"));
    expect(ticks).toContainElement(screen.getByRole("img", { name: "Serve only what is fresh." }));
  });

  it("refuses hint or help without the control as its only child", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(
        <FormLayout>
          <FormField size="medium" hint="x">
            text
          </FormField>
        </FormLayout>,
      ),
    ).toThrow("needs the field's control as its only child");
    spy.mockRestore();
  });

  it.each([
    ["FormField", <FormField size="short">x</FormField>],
    ["FieldGroup", <FieldGroup>x</FieldGroup>],
    ["FormIdentifiers", <FormIdentifiers>x</FormIdentifiers>],
    ["FormChecks", <FormChecks>x</FormChecks>],
  ])("%s outside a FormLayout throws", (name, element) => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(element)).toThrow(`<${name}> must be rendered inside a <FormLayout>`);
    spy.mockRestore();
  });

  it("ends in an action row that keeps the primary action first", () => {
    render(
      <FormLayout data-testid="layout">
        <FormField size="medium">
          <TextInput label="Name" />
        </FormField>
        <FormFooter data-testid="footer">
          <Button type="submit">Save</Button>
          <Button variant="default">Cancel</Button>
        </FormFooter>
      </FormLayout>,
    );
    const footer = screen.getByTestId("footer");
    expect(footer).toHaveClass("form-footer");
    expect(screen.getByTestId("layout").lastElementChild).toBe(footer);
    const names = Array.from(footer.querySelectorAll("button")).map((b) => b.textContent);
    expect(names).toEqual(["Save", "Cancel"]);
  });

  it("serves a dialog with no fields: the action row needs no FormLayout", () => {
    render(
      <FormFooter>
        <Button>Delete</Button>
      </FormFooter>,
    );
    expect(screen.getByRole("button", { name: "Delete" }).parentElement).toHaveClass("form-footer");
  });
});
