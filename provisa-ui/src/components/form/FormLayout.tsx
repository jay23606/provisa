// Copyright (c) 2026 Kenneth Stott
// Canary: f421e7f1-870e-475c-bbe1-9938199a2c82
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1968: the one layout every form uses. Fields flow in a wrapping row and take as many columns
// as the container allows, so no form carries breakpoints of its own; the DOM order is the visual
// order and the keyboard order. The widths live in App.css (`.form-layout`, `.form-field--*`).

import {
  Children,
  cloneElement,
  createContext,
  createElement,
  isValidElement,
  useContext,
  useId,
  type CSSProperties,
  type FormEventHandler,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Tooltip } from "@mantine/core";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";

const FormLayoutContext = createContext(false);

function useInsideFormLayout(component: string): void {
  if (!useContext(FormLayoutContext)) {
    throw new Error(`<${component}> must be rendered inside a <FormLayout> (REQ-1968)`);
  }
}

function classes(...names: (string | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

type LayoutElementProps = Omit<HTMLAttributes<HTMLElement>, "onSubmit"> & {
  onSubmit?: FormEventHandler<HTMLFormElement>;
};

export function FormLayout({
  component = "div",
  className,
  children,
  ...rest
}: LayoutElementProps & { component?: "div" | "form" | "fieldset" }) {
  return (
    <FormLayoutContext.Provider value={true}>
      {createElement(
        component,
        { ...rest, className: classes("form-layout", className) },
        children,
      )}
    </FormLayoutContext.Provider>
  );
}

/**
 * short: numbers, ports, durations, switches, short choices. medium: names, hosts. long: addresses,
 * paths, one-line descriptions. full: multi-line text, editors, tables and sections only.
 */
export type FormFieldSize = "short" | "medium" | "long" | "full";

/** A longer explanation: a (?) immediately after the label, opened by hover, focus or touch. */
function LabelWithHelp({ label, help }: { label: ReactNode; help: string }) {
  return (
    <span className="form-label">
      {label}
      <Tooltip label={help} multiline w={320} events={{ hover: true, focus: true, touch: true }}>
        <span className="form-help" role="img" tabIndex={0} aria-label={help}>
          <CircleHelp size={14} aria-hidden />
        </span>
      </Tooltip>
    </span>
  );
}

type Explainable = { label?: ReactNode; description?: ReactNode };

/**
 * One field of a form. `hint` is a brief explanation (one short sentence) shown BELOW the control;
 * `help` is a longer one, shown only behind a (?) immediately after the label. Nothing is ever
 * rendered between the label and the control, so the controls of a row share a baseline.
 */
export function FormField({
  size,
  hint,
  help,
  className,
  style,
  children,
  ...rest
}: Omit<HTMLAttributes<HTMLDivElement>, "style"> & {
  size: FormFieldSize;
  hint?: string;
  help?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  useInsideFormLayout("FormField");
  let content = children;
  if (hint !== undefined || help !== undefined) {
    const only = Children.toArray(children);
    const control = only.length === 1 ? only[0] : null;
    if (!isValidElement<Explainable>(control)) {
      throw new Error(
        "<FormField hint|help> needs the field's control as its only child (REQ-1968)",
      );
    }
    content = cloneElement(control, {
      ...(hint !== undefined ? { description: hint } : {}),
      ...(help !== undefined
        ? { label: <LabelWithHelp label={control.props.label} help={help} /> }
        : {}),
    });
  }
  return (
    <div
      {...rest}
      style={style}
      className={classes("form-field", `form-field--${size}`, className)}
    >
      {content}
    </div>
  );
}

/**
 * The ticks and switches of a form, together on a line of their own beneath the fields they
 * belong with. Each is its label and an optional (?); no paragraph sits beside a box.
 */
export function FormChecks({ children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  useInsideFormLayout("FormChecks");
  return (
    <div {...rest} className={classes("form-checks", rest.className)}>
      {children}
    </div>
  );
}

/**
 * Fields that belong together (host and port, precision and scale): they wrap as one. With `row`
 * the group takes a line to itself: one entry of a list the form edits.
 */
export function FieldGroup({
  row = false,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { row?: boolean }) {
  useInsideFormLayout("FieldGroup");
  return (
    <div
      {...rest}
      className={classes(
        "form-field-group",
        row ? "form-field-group--row" : undefined,
        rest.className,
      )}
    >
      {children}
    </div>
  );
}

/** The fields that name the object. They sit above the flow, in a section of their own. */
export function FormIdentifiers({ children, ...rest }: HTMLAttributes<HTMLElement>) {
  useInsideFormLayout("FormIdentifiers");
  const { t } = useTranslation();
  const headingId = useId();
  return (
    <section
      {...rest}
      aria-labelledby={headingId}
      className={classes("form-identifiers", rest.className)}
    >
      <h3 id={headingId} className="form-identifiers__heading">
        {t("common.identity")}
      </h3>
      {children}
    </section>
  );
}

/**
 * A form's or dialog's action row: at the bottom, at the start of the line (left in a left-to-right
 * language, right in a right-to-left one), primary action first. Buttons keep their natural width.
 */
export function FormFooter({ children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={classes("form-footer", rest.className)}>
      {children}
    </div>
  );
}
