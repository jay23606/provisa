// Copyright (c) 2026 Kenneth Stott
// Canary: 01ed1c62-49ae-4e2e-a01b-d87ac588dc3c
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { createContext, useContext } from "react";

/** Inside a `FormRead`: the form is drawn read-only, each field its label and its value. */
export const FormReadContext = createContext(false);

/** Whether the form is drawn read-only (inside a `FormRead`). */
export function useFormRead(): boolean {
  return useContext(FormReadContext);
}

/**
 * A form split into sections, one in view at a time (a detail panel's section tabs): which is in
 * view, the section a field not marked otherwise belongs to, and the sections the form has for
 * what it shows -- each section a rendered field or `FormSection` names is noted here.
 */
export interface FormSectionsState {
  active: string;
  fallback: string;
  seen: Set<string>;
}

export const FormSectionsContext = createContext<FormSectionsState | null>(null);

/** The section of the `FormSection` a field is inside, if any. */
export const FormSectionIdContext = createContext<string | null>(null);

/** Whether a field of ``section`` (else its `FormSection`'s, else the form's first) is in view;
 *  notes the section as one the form has. Outside `FormSections`, every field is. */
export function useFormSectionInView(section?: string): boolean {
  const state = useContext(FormSectionsContext);
  const inherited = useContext(FormSectionIdContext);
  if (state === null) return true;
  const id = section ?? inherited ?? state.fallback;
  state.seen.add(id);
  return state.active === id;
}
