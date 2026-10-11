// Copyright (c) 2026 Kenneth Stott
// Canary: f00d1057-1dc4-48eb-83b1-e3f5a5bb2354
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Leaving a form that is open in a detail panel (SplitPane) with changes that are not saved
// asks first: "Discard your changes?". One mechanism for every page with a panel:
//
// - A form says whether it has changed since it opened with ONE line, `usePanelDirty(dirty, what)`
//   -- `what` names what is being edited, for the question.
// - Whatever would leave the form runs through `guard(go)`: `go` runs at once when nothing has
//   changed, and only after "Discard" when something has. The panel guards its own close and
//   back, and a row of a list beside it (`ListRow`) guards its own click; a page guards the
//   openers of its other forms through the same `guard`, from `usePanelLeave()`.
// - Save and the form's own Cancel are not leaving: neither asks.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface PanelLeave {
  /** Run `go` now, or after the reader chooses Discard when the open form has changes. */
  guard: (go: () => void) => void;
  /** The form's signal: what is being edited while it has unsaved changes, else null. */
  setDirty: (what: string | null) => void;
  /** What the question is about while it is being asked, else null. */
  asking: string | null;
  /** The reader's answer: Discard runs what was waiting; Cancel drops it and stays. */
  answer: (discard: boolean) => void;
}

export const PanelLeaveContext = createContext<PanelLeave | null>(null);

/** The state of one panel's leave question. A page calls it once and gives it to its SplitPane
 * (`leave`), so the page's own openers can use the same `guard`. */
export function usePanelLeave(): PanelLeave {
  const dirty = useRef<string | null>(null);
  const waiting = useRef<(() => void) | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const setDirty = useCallback((what: string | null) => {
    dirty.current = what;
  }, []);
  const guard = useCallback((go: () => void) => {
    if (dirty.current === null) {
      go();
      return;
    }
    waiting.current = go;
    setAsking(dirty.current);
  }, []);
  const answer = useCallback((discard: boolean) => {
    const go = waiting.current;
    waiting.current = null;
    setAsking(null);
    if (!discard || go === null) return;
    // The edit is dropped: nothing is left to ask about, whatever unmounts when.
    dirty.current = null;
    go();
  }, []);
  return useMemo(() => ({ guard, setDirty, asking, answer }), [guard, setDirty, asking, answer]);
}

/** A form's one line: it has changed since it opened (`dirty`), and `what` it is editing. Outside
 * a panel it does nothing. The signal is withdrawn when the form closes, however it closes. */
export function usePanelDirty(dirty: boolean, what: string): void {
  const leave = useContext(PanelLeaveContext);
  const setDirty = leave?.setDirty;
  useEffect(() => {
    if (!setDirty) return;
    setDirty(dirty ? what : null);
    return () => setDirty(null);
  }, [setDirty, dirty, what]);
}

/** For whatever would leave an open form (a list's row): `guard(go)` of the panel it is beside,
 * or one that runs `go` at once where there is no panel. */
export function useLeaveGuard(): (go: () => void) => void {
  const leave = useContext(PanelLeaveContext);
  return leave ? leave.guard : run;
}

function run(go: () => void): void {
  go();
}
