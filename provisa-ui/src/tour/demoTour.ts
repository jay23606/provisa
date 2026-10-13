// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * REQ-2010: a named demo's own tour, the demo's track. Its steps are written with the demo
 * (demo/named/<name>/tour.yaml) and reach the UI on /setup/status; each names a page and one object
 * of the demo, and is turned here into a step of the tour runner. Their words are
 * tour.steps.<key>, like every other step's.
 */
import type { Capability } from "../types/auth";
import type { ExampleQuery } from "../api/setup";
import type { TourStep } from "./tourSteps";

/** One step of tour.yaml, as the server sends it: its page, and exactly one target. */
export interface DemoTourStepDef {
  key: string;
  route?: string;
  capability?: Capability;
  /** A source, by id: its row on the Sources page. */
  source?: string;
  /** A relationship, by alias: its row on the Relationships page. */
  relationship?: string;
  /** An example query of the demo, by name: opened in a new GraphiQL tab and run. */
  example?: string;
  /** A statement: opened in a new SQL explorer tab and run. */
  sql?: string;
  /** A glossary term, by name: opened on the Glossary page, its definition and links shown. */
  term?: string;
  /** A role (or "all"): shown in the SQL explorer's run-as picker, picked on Next. */
  role?: string;
}

/** Answers that come from the server are slow on a loaded demo; a run's result waits this long. */
const RESULT_WAIT_MS = 60000;
// The SQL explorer's own run-as picker (REQ-1013), not the app-wide role: it is what the explorer's
// statements run as.
const RUN_AS = '[data-testid="sql-role"]';
const SQL_RESULT_ROW = '.sql-results-table tbody tr:not([data-testid="results-grid-empty"])';

export function demoTourSteps(
  defs: readonly DemoTourStepDef[],
  examples: readonly ExampleQuery[],
): TourStep[] {
  return defs.map((def) => {
    const page = {
      key: def.key,
      ...(def.route !== undefined ? { route: def.route, capability: def.capability } : {}),
    };
    if (def.source !== undefined) {
      return { ...page, element: `[data-testid="sources-row-${def.source}"]` };
    }
    if (def.relationship !== undefined) {
      return { ...page, element: `[data-tour-relationship="${def.relationship}"]` };
    }
    if (def.example !== undefined) {
      const example = examples.find((e) => e.name === def.example);
      // The server sends the demo's tour and its examples together; a step naming an example the
      // demo does not ship is a defect of the demo, which tests/unit/test_named_demo_tour.py holds.
      if (example === undefined) {
        throw new Error(`Tour: step ${def.key} names example "${def.example}", not shipped`);
      }
      return {
        ...page,
        openQuery: { stateKey: "query", text: example.query },
        element: ".graphiql-response",
        waitMs: RESULT_WAIT_MS,
      };
    }
    if (def.sql !== undefined) {
      return {
        ...page,
        openQuery: { stateKey: "sql", text: def.sql },
        // Its rows, not the table: the grid of an unrun tab is a table that says it has none.
        readySelector: SQL_RESULT_ROW,
        element: ".sql-results-table",
        waitMs: RESULT_WAIT_MS,
      };
    }
    if (def.term !== undefined) {
      return {
        ...page,
        clickBefore: `[data-glossary-term="${def.term}"]`,
        element: '[data-testid="glossary-detail"]',
      };
    }
    if (def.role !== undefined) {
      return {
        ...page,
        element: RUN_AS,
        chooseOnNext: { open: RUN_AS, option: `[data-sql-role-option="${def.role}"]` },
      };
    }
    throw new Error(`Tour: step ${def.key} names no target`);
  });
}
