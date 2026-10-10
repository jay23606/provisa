// Copyright (c) 2026 Kenneth Stott
// Canary: 920ed371-ac39-490c-8db5-afdc7347ed97
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1968: the form rules, read off the parsed TSX of one file. formLayoutGuard.test.ts runs
// them over every component; the rules are here so the guard can also be shown to fail.

import ts from "typescript";

export type FormRule =
  /** A single-line field stretched across the form. */
  | "full-width-single-line"
  /** A form laying its fields out itself: its own grid, or a field outside a FormField. */
  | "outside-shared-layout"
  /** Action buttons aligned anywhere but the start of the line. */
  | "actions-not-at-start"
  /** A button stretched by `fullWidth` or by its container. */
  | "button-stretched";

export interface FormViolation {
  rule: FormRule;
  line: number;
  detail: string;
}

export interface FormRuleOptions {
  /** The file holds controls that are not a form (a search box, a toolbar, a query editor). */
  notAForm?: boolean;
  /** Buttons that may fill their container: each is matched by a substring of its own JSX. */
  stretchedButtonExceptions?: readonly string[];
}

const SINGLE_LINE = new Set([
  "TextInput",
  "NumberInput",
  "PasswordInput",
  "Select",
  "MultiSelect",
  "Autocomplete",
  "NativeSelect",
  "TagsInput",
  "Checkbox",
  "Switch",
  "input",
  "select",
]);
const MULTI_LINE = new Set(["Textarea", "JsonInput", "textarea"]);
const TABLE_CELLS = new Set(["Table.Td", "Table.Th", "td", "th"]);
/** Elements that render their child in place, so the child's layout parent is theirs. */
const TRANSPARENT = new Set(["Tooltip", "CapabilityGate"]);
const END_JUSTIFY = /^(flex-end|end|right)$/;
const SPREAD_JUSTIFY = /^(space-between|space-around|space-evenly|center)$/;
const ROW_SPAN = /gridColumn:\s*["'`]1\s*\/\s*-1["'`]/;

type JsxEl = ts.JsxElement | ts.JsxSelfClosingElement;

function isJsxEl(n: ts.Node): n is JsxEl {
  return ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n);
}

function opening(n: JsxEl): ts.JsxOpeningElement | ts.JsxSelfClosingElement {
  return ts.isJsxElement(n) ? n.openingElement : n;
}

function tagOf(n: JsxEl): string {
  return opening(n).tagName.getText();
}

/** The source text of an attribute's value, `"true"` for a bare attribute, undefined when absent. */
function attr(n: JsxEl, name: string): string | undefined {
  for (const a of opening(n).attributes.properties) {
    if (ts.isJsxAttribute(a) && a.name.getText() === name) {
      if (!a.initializer) return "true";
      if (ts.isStringLiteral(a.initializer)) return a.initializer.text;
      if (ts.isJsxExpression(a.initializer) && a.initializer.expression) {
        const e = a.initializer.expression;
        return ts.isStringLiteralLike(e) ? e.text : e.getText();
      }
      return a.initializer.getText();
    }
  }
  return undefined;
}

export function checkFormRules(
  fileName: string,
  source: string,
  options: FormRuleOptions = {},
): FormViolation[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations: FormViolation[] = [];
  const report = (rule: FormRule, node: ts.Node, detail: string) =>
    violations.push({
      rule,
      line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1,
      detail,
    });

  // Style objects declared once and passed by name: `const full = { gridColumn: "1 / -1" }`.
  const rowSpanStyles = new Set<string>();
  const collectStyles = (n: ts.Node) => {
    if (
      ts.isVariableDeclaration(n) &&
      ts.isIdentifier(n.name) &&
      n.initializer &&
      ROW_SPAN.test(n.initializer.getText())
    ) {
      rowSpanStyles.add(n.name.text);
    }
    ts.forEachChild(n, collectStyles);
  };
  collectStyles(sf);

  const spansRow = (n: JsxEl): boolean => {
    const style = attr(n, "style");
    return style !== undefined && (ROW_SPAN.test(style) || rowSpanStyles.has(style));
  };

  /** The element that lays this one out: through fragments, conditions, `.map` and wrappers. */
  const layoutParent = (n: ts.Node): JsxEl | undefined => {
    for (let p = n.parent; p; p = p.parent) {
      if (ts.isJsxAttribute(p)) return undefined;
      if (ts.isJsxElement(p)) {
        if (TRANSPARENT.has(tagOf(p))) continue;
        return p;
      }
      if (ts.isArrowFunction(p) || ts.isFunctionExpression(p)) {
        if (!ts.isCallExpression(p.parent)) return undefined;
      } else if (ts.isFunctionDeclaration(p) || ts.isMethodDeclaration(p)) {
        return undefined;
      }
    }
    return undefined;
  };

  const hasAncestor = (n: ts.Node, tags: Set<string>): boolean => {
    for (let p = n.parent; p; p = p.parent) {
      if (ts.isJsxElement(p) && tags.has(tagOf(p))) return true;
    }
    return false;
  };

  /** The elements an element lays out directly, seen the way `layoutParent` sees them. */
  const layoutChildren = (parent: ts.JsxElement): JsxEl[] => {
    const found: JsxEl[] = [];
    const visit = (n: ts.Node) => {
      if (isJsxEl(n) && n !== parent) {
        if (layoutParent(n) === parent) found.push(n);
        if (!TRANSPARENT.has(tagOf(n))) return;
      }
      if (ts.isJsxAttribute(n)) return;
      ts.forEachChild(n, visit);
    };
    visit(parent);
    return found;
  };

  const isExceptedButton = (n: JsxEl): boolean =>
    (options.stretchedButtonExceptions ?? []).some((marker) => n.getText().includes(marker));

  const checkControl = (n: JsxEl, tag: string) => {
    if (attr(n, "type") === "hidden" || attr(n, "type") === "file") return;
    const single = SINGLE_LINE.has(tag);
    if (single && spansRow(n)) {
      report("full-width-single-line", n, `<${tag}> spans the row`);
    }
    if (options.notAForm || hasAncestor(n, TABLE_CELLS)) return;
    if (!hasAncestor(n, new Set(["FormField"]))) {
      report("outside-shared-layout", n, `<${tag}> is not inside a <FormField>`);
    }
  };

  const checkFormField = (n: ts.JsxElement) => {
    if (attr(n, "size") !== "full") return;
    const children = layoutChildren(n);
    if (children.length === 1 && SINGLE_LINE.has(tagOf(children[0]))) {
      report("full-width-single-line", n, `<${tagOf(children[0])}> in a full-width FormField`);
    }
  };

  const checkActionRow = (n: ts.JsxElement, tag: string) => {
    const className = attr(n, "className") ?? "";
    if (/\bmodal-actions\b/.test(className)) {
      report("actions-not-at-start", n, "modal-actions aligns its buttons to the end");
      return;
    }
    const style = attr(n, "style") ?? "";
    const styleJustify = /justifyContent:\s*["'`]([a-z-]+)["'`]/.exec(style)?.[1];
    const justify = tag === "Group" || tag === "Flex" ? attr(n, "justify") : styleJustify;
    if (justify === undefined) return;
    const children = layoutChildren(n);
    const buttons = children.filter((c) => tagOf(c) === "Button");
    if (buttons.length === 0) return;
    const onlyButtons = buttons.length === children.length;
    if (END_JUSTIFY.test(justify) || (SPREAD_JUSTIFY.test(justify) && onlyButtons)) {
      report("actions-not-at-start", n, `buttons in a row justified "${justify}"`);
    }
  };

  const checkButton = (n: JsxEl) => {
    if (isExceptedButton(n)) return;
    if (attr(n, "fullWidth") !== undefined && attr(n, "fullWidth") !== "false") {
      report("button-stretched", n, "<Button fullWidth>");
      return;
    }
    if (spansRow(n)) {
      report("button-stretched", n, "<Button> spans the row");
      return;
    }
    const parent = layoutParent(n);
    if (!parent) return;
    const parentTag = tagOf(parent);
    const style = attr(n, "style") ?? "";
    const keepsOwnWidth = attr(n, "w") !== undefined || /alignSelf|justifySelf/.test(style);
    if (parentTag === "Stack") {
      const align = attr(parent, "align");
      if ((align === undefined || align === "stretch") && !keepsOwnWidth) {
        report("button-stretched", n, "<Button> is a direct child of a stretching <Stack>");
      }
    } else if (
      /\bform-card\b/.test(attr(parent, "className") ?? "") &&
      parentTag !== "FormLayout"
    ) {
      if (!keepsOwnWidth) {
        report("button-stretched", n, "<Button> is a direct child of a form-card grid");
      }
    }
  };

  const visit = (n: ts.Node) => {
    if (isJsxEl(n)) {
      const tag = tagOf(n);
      if (SINGLE_LINE.has(tag) || MULTI_LINE.has(tag)) checkControl(n, tag);
      if (tag === "Button") checkButton(n);
      if (ts.isJsxElement(n)) {
        if (tag === "FormField") checkFormField(n);
        checkActionRow(n, tag);
      }
      if (tag !== "FormLayout" && /\bform-(card|row)\b/.test(attr(n, "className") ?? "")) {
        report("outside-shared-layout", n, `<${tag} className="${attr(n, "className")}">`);
      }
      const isControl = SINGLE_LINE.has(tag) || MULTI_LINE.has(tag);
      if (!isControl && tag !== "Button" && spansRow(n)) {
        report("outside-shared-layout", n, `<${tag}> placed with gridColumn`);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return violations.sort((a, b) => a.line - b.line);
}
