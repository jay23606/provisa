// Copyright (c) 2026 Kenneth Stott
// Canary: 528951ae-3881-418a-b074-e27afc6ee426
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * The Schema Explorer's graph is GraphQL Voyager, a library that draws in a document of its own
 * (an iframe) with its own stylesheet: white panels, teal nodes, Helvetica. This is the sheet
 * that follows it in that document and gives it the app's fonts and colours -- nothing else: no
 * layout, no spacing, no control is changed.
 *
 * The values are the app's own theme tokens, handed in as custom properties (`voyagerThemeVars`)
 * and rewritten in place when the app's colour scheme changes, so the graph keeps its position.
 *
 * It depends on names the library owns. `VOYAGER_CLASSES` are the classes of its stylesheet this
 * sheet overrides and `MUI_COMPONENTS` the Material UI components whose controls it recolours; a
 * test checks both against the installed package, so an upgrade that renames one fails there
 * instead of quietly losing the theme.
 */

/** The app's tokens the theme is made of, by the name each has in the app's stylesheet. */
export const THEME_TOKENS = [
  "--bg",
  "--surface",
  "--surface-alt",
  "--border",
  "--text",
  "--text-muted",
  "--primary",
  "--primary-hover",
  "--primary-strong",
  "--destructive",
  "--font",
] as const;

/** The id of the style element in Voyager's document that holds the tokens' values. */
export const VOYAGER_VARS_ID = "provisa-theme-vars";

/** The tokens as they are now on the app's root element, as one rule for Voyager's document. */
export function voyagerThemeVars(root: Element): string {
  const now = getComputedStyle(root);
  return `:root{${THEME_TOKENS.map((name) => `${name}:${now.getPropertyValue(name).trim()}`).join(";")}}`;
}

/** Classes of Voyager's own stylesheet that the theme overrides. */
export const VOYAGER_CLASSES = [
  "graphql-voyager",
  "doc-panel",
  "contents",
  "menu-content",
  "doc-wrapper",
  "doc-navigation",
  "back",
  "active",
  "header",
  "eye-button",
  "field-name",
  "type-name",
  "value-name",
  "arg-name",
  "default-value",
  "arg-wrap",
  "arg",
  "arg-description",
  "doc-alert-text",
  "type-doc",
  "loading",
  "doc-category",
  "item",
  "title",
  "description-box",
  "type-info-popover",
  "typelist-item",
  "type-link",
  "node",
  "type-title",
  "field",
  "selected",
  "edge",
  "hover-path",
  "highlighted",
  "hovered",
] as const;

/** Material UI components Voyager builds its controls from; their class names start with these. */
export const MUI_COMPONENTS = [
  "MuiInputBase",
  "MuiInput",
  "MuiSelect",
  "MuiCheckbox",
  "MuiIconButton",
  "MuiSvgIcon",
  "MuiTypography",
  "MuiPaper",
  "MuiMenuItem",
] as const;

/* Every rule starts at `html` so it outranks the library's own one-class rules whatever the
 * order the sheets load in. Colours set as SVG attributes (Graphviz writes fill, stroke and
 * font-family on each shape) yield to any rule, so the graph is recoloured here too. */
export const VOYAGER_THEME_CSS = `
html body { background: var(--bg); }
html .graphql-voyager { font-family: var(--font); color: var(--text); background: var(--bg); }

/* The doc panel. */
html .graphql-voyager > .doc-panel,
html .doc-wrapper,
html .doc-panel > .contents,
html .type-doc > div,
html .type-info-popover,
html .graphql-voyager > .menu-content { background: var(--surface); color: var(--text); border-color: var(--border); }
html .doc-navigation { border-bottom-color: var(--border); }
html .doc-navigation > .back { color: var(--text); }
html .doc-navigation > .back:before { border-left-color: var(--text); border-top-color: var(--text); }
html .doc-navigation > .active { color: var(--primary-hover); }
html .doc-navigation > .header,
html .type-doc > .loading,
html .doc-category > .title,
html .doc-category > .item,
html .description-box.-no-description,
html .arg-wrap.-expanded .arg-description,
html .type-name + .field-name::before { color: var(--text-muted); }
html .doc-category > .title { border-bottom-color: var(--border); }
html .doc-category > .item:nth-child(odd) { background-color: color-mix(in srgb, var(--surface-alt) 45%, transparent); }
html .doc-category > .item:hover { background-color: var(--surface-alt); }
html .doc-category > .item.-selected { background-color: var(--surface-alt); border-left-color: var(--primary); }
html .doc-category > .item.-with-args:before { border-top-color: var(--text-muted); }
html .description-box blockquote { border-left-color: var(--border); }
html .eye-button svg path:not([fill]) { fill: var(--primary-hover); }
html .field-name,
html .value-name { color: var(--text); }
html .arg-name,
html .arg-wrap > .arg > .default-value { color: var(--text-muted); }
html .doc-alert-text { color: var(--destructive); }
html .type-name.-input-obj,
html .type-name.-object { color: var(--primary-hover); }
html .type-name.-input-obj:hover,
html .type-name.-object:hover { color: var(--primary); }
html .type-name.-scalar,
html .type-name.-built-in,
html .type-name.-scalar:hover,
html .type-name.-built-in:hover { color: var(--text-muted); }
html .typelist-item.-root .type-name:after { background: var(--primary-strong); color: #fff; }
/* A search match: the library leaves it the browser's yellow. */
html .graphql-voyager mark { background: color-mix(in srgb, var(--primary) 40%, transparent); color: inherit; }

/* The library's controls (Material UI): the search box, the root selector, the options. */
html .MuiTypography-root,
html .MuiInputBase-root,
html .MuiMenuItem-root { font-family: var(--font); color: var(--text); }
html .MuiInputBase-input::placeholder { color: var(--text-muted); opacity: 1; }
html .MuiInput-root:before { border-bottom-color: var(--border); }
html .MuiInput-root:hover:not(.Mui-disabled):before { border-bottom-color: var(--text-muted); }
html .MuiInput-root:after { border-bottom-color: var(--primary); }
html .MuiSelect-icon,
html .MuiInputBase-root .MuiSvgIcon-root { color: var(--text-muted); }
html .MuiCheckbox-root { color: var(--text-muted); }
html .MuiCheckbox-root.Mui-checked,
html .MuiIconButton-root { color: var(--primary-hover); }
html .MuiPaper-root { background-color: var(--surface); color: var(--text); }
html .MuiMenuItem-root:hover,
html .MuiMenuItem-root.Mui-selected { background-color: var(--surface-alt); }

/* The graph. */
html .graphql-voyager svg text { font-family: var(--font); fill: var(--text); }
/* A node's outline is the dimmed-text colour, not the border colour: on the page background a
 * border-coloured line is too faint to carry a node that is not selected. */
html .node polygon { stroke: var(--text-muted); fill: var(--surface); }
html .node .type-title polygon { fill: var(--surface-alt); stroke: var(--text-muted); }
html .node .type-title text { fill: var(--text); }
html .node.selected polygon { stroke: var(--primary); }
html .node.selected .type-title polygon { fill: var(--primary-strong); }
html .node.selected .type-title text { fill: #fff; }
html .field.selected > polygon { fill: color-mix(in srgb, var(--primary) 30%, transparent); }
html .graphql-voyager svg text.type-link,
html .type-link { fill: var(--primary-hover); }
html .type-link:hover { fill: var(--primary); }
html .edge path:not(.hover-path) { stroke: var(--text-muted); }
html .edge polygon { fill: var(--text-muted); stroke: var(--text-muted); }
html .graphql-voyager svg .edge text { fill: var(--text-muted); }
html .edge.highlighted path:not(.hover-path),
html .edge.hovered path:not(.hover-path),
html .edge:hover path:not(.hover-path) { stroke: var(--primary-hover); }
html .edge.highlighted polygon,
html .edge.hovered polygon,
html .edge:hover polygon { stroke: var(--primary-hover); fill: var(--primary-hover); }
html .edge.selected path:not(.hover-path) { stroke: var(--destructive); }
html .edge.selected polygon { stroke: var(--destructive); fill: var(--destructive); }
`;
