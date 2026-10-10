// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Which topic of a column the column editors show: see ColumnTabs.

import { useState } from "react";

export type ColumnTab = "naming" | "type" | "access";
export const COLUMN_TABS: ColumnTab[] = ["naming", "type", "access"];

/** The tab in view; a form that hides a topic (no right to see grants) passes the ones it shows. */
export function useColumnTab(shown: ColumnTab[] = COLUMN_TABS) {
  const [tab, setTab] = useState<ColumnTab>(shown[0]);
  return [shown.includes(tab) ? tab : shown[0], setTab] as const;
}
