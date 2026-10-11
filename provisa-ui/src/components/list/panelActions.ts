// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// Where a detail panel's content puts its actions: the pinned head of the panel it is in.
// `undefined` means "not in a panel" (render the actions in place); `null` means the panel's head
// is not mounted yet.

import { createContext } from "react";

export const PanelActionsContext = createContext<HTMLElement | null | undefined>(undefined);
