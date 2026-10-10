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
  createContext,
  createElement,
  useContext,
  useId,
  type CSSProperties,
  type FormEventHandler,
  type HTMLAttributes,
  type ReactNode,
} from "react";
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
      {createElement(component, { ...rest, className: classes("form-layout", className) }, children)}
    </FormLayoutContext.Provider>
  );
}

/**
 * short: numbers, ports, durations, switches, short choices. medium: names, hosts. long: addresses,
 * paths, one-line descriptions. full: multi-line text, editors, tables and sections only.
 */
export type FormFieldSize = "short" | "medium" | "long" | "full";

export function FormField({
  size,
  className,
  style,
  children,
  ...rest
}: Omit<HTMLAttributes<HTMLDivElement>, "style"> & {
  size: FormFieldSize;
  style?: CSSProperties;
  children: ReactNode;
}) {
  useInsideFormLayout("FormField");
  return (
    <div {...rest} style={style} className={classes("form-field", `form-field--${size}`, className)}>
      {children}
    </div>
  );
}

/** Fields that belong together (host and port, precision and scale): they wrap as one. */
export function FieldGroup({ children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  useInsideFormLayout("FieldGroup");
  return (
    <div {...rest} className={classes("form-field-group", rest.className)}>
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
