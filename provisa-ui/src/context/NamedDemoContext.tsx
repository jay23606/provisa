// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { createContext, useContext } from "react";
import type { ExampleQuery } from "../api/setup";
import type { DemoTourStepDef } from "../tour/demoTour";

/** The named demo this deployment was started as, from /setup/status (App.tsx provides it): its
 * name, its example GraphQL queries (REQ-2009) and its own tour (REQ-2010). */
export interface NamedDemo {
  name: string | null;
  exampleQueries: ExampleQuery[];
  tour: DemoTourStepDef[];
}

/** A page rendered outside the app (a component test) has read no status: no named demo. */
export const NO_NAMED_DEMO: NamedDemo = { name: null, exampleQueries: [], tour: [] };

export const NamedDemoContext = createContext<NamedDemo>(NO_NAMED_DEMO);

export function useNamedDemo(): NamedDemo {
  return useContext(NamedDemoContext);
}
