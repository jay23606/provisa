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
  useState,
  type CSSProperties,
  type FormEventHandler,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Button, Loader } from "@mantine/core";
import { Check, CircleHelp, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";
import { PanelActionsContext, PanelNoticeContext } from "../list/panelActions";
import { useHelpNaming } from "./useHelpNaming";
import { Tip } from "../Tip";

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

/**
 * A label with its longer explanation: the text, the required mark right after the text, then a
 * (?) opened by hover, focus or touch. The one help glyph of every form.
 *
 * The control is NAMED by the text alone and DESCRIBED by the help: its owner points
 * `aria-labelledby` at `textId` and gives the help as its description, so the (?) inside the
 * label is not read as part of the name.
 */
export function LabelWithHelp({
  label,
  help,
  required = false,
  textId,
}: {
  label: ReactNode;
  help: string;
  required?: boolean;
  textId?: string;
}) {
  return (
    <span className="form-label">
      <span>
        <span id={textId}>{label}</span>
        {required && (
          <span className="form-required" aria-hidden>
            {" *"}
          </span>
        )}
      </span>
      {/* The one tooltip of the application. It opens at once: the (?) exists only to be asked,
          so nothing is gained by waiting. Its name already is the help, so it is not also its
          description. */}
      <Tip text={help} openDelay={0} named>
        <span className="form-help" role="img" tabIndex={0} aria-label={help}>
          <CircleHelp size={14} aria-hidden />
        </span>
      </Tip>
    </span>
  );
}

type Explainable = {
  label?: ReactNode;
  description?: ReactNode;
  required?: boolean;
  withAsterisk?: boolean;
  "aria-label"?: string;
};

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
  const { textId, naming } = useHelpNaming(help);
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
        ? {
            // The mark is drawn with the text, so it comes before the (?); the control keeps
            // `required` and only stops drawing a second mark after the icon.
            label: (
              <LabelWithHelp
                label={control.props.label}
                help={help}
                required={control.props.required === true}
                textId={textId}
              />
            ),
            withAsterisk: false,
            // A control that states its own accessible name keeps it; the help is still its
            // description.
            ...(control.props["aria-label"] === undefined ? naming : { "aria-description": help }),
          }
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
 *
 * `column`: a checklist — one tick to a line, where the ticks ARE the form (a list of things to
 * accept or leave out) rather than a few settings beside its fields.
 */
export function FormChecks({
  column = false,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { column?: boolean }) {
  useInsideFormLayout("FormChecks");
  return (
    <div
      {...rest}
      className={classes("form-checks", column ? "form-checks--column" : undefined, rest.className)}
    >
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

type ButtonExtras = { "data-testid"?: string; disabled?: boolean };

/**
 * A form's or dialog's action row: at the bottom, at the start of the line (left in a left-to-right
 * language, right in a right-to-left one). It owns the form's Save and Cancel, so every form has
 * the same two: the check and the word "Save", then the cross and the word "Cancel".
 *
 * From the press until the save settles Save shows a spinner in place of its icon and both buttons
 * are disabled. A form says it is saving in one of two ways: `onSave` returns the save's promise,
 * or the form passes `saving` (a form that submits through `<form onSubmit>` sets `submit`).
 * Other actions of the row go in as children, after the two. A form whose first action is not a
 * save (Generate, Run, Delete) passes it as `action`: it takes Save's place, before Cancel, and
 * keeps its own word.
 *
 * `panel`: the form is a detail panel's content, and these are the panel's actions while it is
 * open. In a panel (`SplitPane`) the same two buttons then sit in its pinned head beside the
 * name -- borderless and compact, so they cost no height -- in place of a row at the form's foot;
 * outside a panel a form that says `panel` keeps the row at its foot. One implementation, the
 * same test ids either way. `problem` is what the form has to say of a save that did not go
 * through: in a panel a line under its head, else a line above the row.
 *
 * `form`: the id of the <form> a `submit` Save belongs to. In a panel's head Save sits outside
 * the form's own element, where a submit button submits nothing; naming the form makes it that
 * form's submit wherever it sits, so the form's required-field checks and its onSubmit run.
 */
export function FormFooter({
  onSave,
  onCancel,
  submit = false,
  saving = false,
  saveProps,
  cancelProps,
  action,
  panel = false,
  problem,
  form,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & {
  action?: ReactNode;
  onSave?: () => unknown;
  onCancel?: () => void;
  submit?: boolean;
  saving?: boolean;
  saveProps?: ButtonExtras;
  cancelProps?: ButtonExtras;
  panel?: boolean;
  problem?: ReactNode;
  form?: string;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const head = useContext(PanelActionsContext);
  const notice = useContext(PanelNoticeContext);
  const inHead = panel && head !== undefined;
  const busy = saving || pending;
  const save = () => {
    const result = onSave?.();
    if (result instanceof Promise) {
      setPending(true);
      // Settled either way: a refused save returns the button to rest, and the form shows why.
      void result.then(
        () => setPending(false),
        () => setPending(false),
      );
    }
  };
  // In a panel's head the two are borderless and compact; the words and icons are the same.
  const inHeadLook = inHead ? ({ variant: "subtle", size: "compact-sm" } as const) : {};
  const said = problem ? (
    <div className="form-problem" role="alert" data-testid="form-problem">
      {problem}
    </div>
  ) : null;
  const buttons = (
    <>
      {(onSave !== undefined || submit) && (
        <Button
          {...inHeadLook}
          {...saveProps}
          // In a panel's head both are borderless: the tint is what says which is the primary.
          data-primary={inHead || undefined}
          form={form}
          type={submit ? "submit" : "button"}
          onClick={submit ? undefined : save}
          leftSection={busy ? <Loader size={14} color="currentColor" /> : <Check size={14} />}
          disabled={busy || saveProps?.disabled === true}
          data-saving={busy || undefined}
        >
          {t("common.save")}
        </Button>
      )}
      {action}
      {onCancel !== undefined && (
        <Button
          variant="default"
          {...inHeadLook}
          {...cancelProps}
          type="button"
          onClick={onCancel}
          leftSection={<X size={14} />}
          disabled={busy || cancelProps?.disabled === true}
        >
          {t("common.cancel")}
        </Button>
      )}
      {children}
    </>
  );
  if (inHead) {
    // The head is not mounted on the first pass; the actions appear with it on the next.
    return (
      <>
        {head !== null &&
          createPortal(
            <div
              {...rest}
              style={undefined}
              className={classes("form-footer", "form-footer--head", rest.className)}
            >
              {buttons}
            </div>,
            head,
          )}
        {said !== null && notice && createPortal(said, notice)}
      </>
    );
  }
  return (
    <div {...rest} className={classes("form-footer", rest.className)}>
      {said}
      {buttons}
    </div>
  );
}
