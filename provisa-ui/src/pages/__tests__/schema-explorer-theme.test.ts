// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The Schema Explorer's theme overrides a library's stylesheet by the library's own names. These
// tests hold the theme to the installed package: an upgrade that renames a class or drops a
// component fails here, instead of quietly losing the theme.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MUI_COMPONENTS,
  THEME_TOKENS,
  VOYAGER_CLASSES,
  VOYAGER_THEME_CSS,
  voyagerThemeVars,
} from "../schemaExplorerTheme";

const ui = resolve(__dirname, "../../..");
const read = (path: string) => readFileSync(resolve(ui, path), "utf8");
const installedCss = read("node_modules/graphql-voyager/dist/voyager.css");
const servedCss = read("public/voyager/voyager.css");
const servedJs = read("public/voyager/voyager.standalone.js");

/** Every class name a stylesheet's selectors use. */
const classesOf = (css: string) =>
  new Set(
    [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{[^}]*\}/g)].flatMap(([, sel]) =>
      [...sel.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)].map(([, name]) => name),
    ),
  );

describe("the Schema Explorer's theme and the library it themes", () => {
  it("serves the stylesheet of the installed package", () => {
    expect(servedCss).toBe(installedCss);
  });

  it("overrides only classes the library's stylesheet has", () => {
    const theirs = classesOf(installedCss);
    expect(VOYAGER_CLASSES.filter((name) => !theirs.has(name))).toEqual([]);
  });

  it("recolours only Material UI components the library's bundle carries", () => {
    expect(MUI_COMPONENTS.filter((name) => !servedJs.includes(`"${name}"`))).toEqual([]);
  });

  it("names every library class it uses in its lists, so the two checks above see them all", () => {
    const listed = new Set<string>([...VOYAGER_CLASSES]);
    const unlisted = [...classesOf(VOYAGER_THEME_CSS)].filter(
      (name) =>
        !listed.has(name) &&
        !name.startsWith("-") && // a modifier of a listed class (.type-name.-object)
        !name.startsWith("Mui-") && // a Material UI state (.Mui-checked)
        !MUI_COMPONENTS.some((component) => name.startsWith(`${component}-`)),
    );
    expect(unlisted).toEqual([]);
  });

  it("takes every colour and font from the app's tokens", () => {
    const used = new Set([...VOYAGER_THEME_CSS.matchAll(/var\((--[\w-]+)\)/g)].map(([, n]) => n));
    expect([...used].filter((name) => !(THEME_TOKENS as readonly string[]).includes(name))).toEqual(
      [],
    );
    // White on the primary fill is the one literal: the app's own rule for text on that fill.
    const literals = VOYAGER_THEME_CSS.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? [];
    expect([...new Set(literals)]).toEqual(["#fff"]);
  });

  it("hands the tokens over with the values they have on the app's root", () => {
    const root = document.createElement("div");
    root.style.setProperty("--bg", "#0f1117");
    root.style.setProperty("--font", "system-ui, sans-serif");
    document.body.append(root);
    const rule = voyagerThemeVars(root);
    expect(rule).toContain("--bg:#0f1117");
    expect(rule).toContain("--font:system-ui, sans-serif");
    root.remove();
  });
});
