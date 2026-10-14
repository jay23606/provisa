// Copyright (c) 2026 Kenneth Stott
// Canary: 7e1b4d93-0a62-4f58-9c27-3d8f6b2a5e10
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/* eslint-disable react-hooks/refs --
   A prev-value ref gates the documented render-phase setState on a prop change (moved here
   unchanged from GraphFrame, which disables the rule for the same pattern). */
import { useRef, useState } from "react";

/** A frame's table view column widths: 180 each, and back to that when its columns change. */
export function useColumnWidths(columns: string[]) {
  const [widths, setWidths] = useState<number[]>(() => columns.map(() => 180));
  const prevColumnsKey = useRef(columns.join(","));
  if (columns.join(",") !== prevColumnsKey.current) {
    prevColumnsKey.current = columns.join(",");
    setWidths(columns.map(() => 180));
  }
  return [widths, setWidths] as const;
}
