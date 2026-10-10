// Copyright (c) 2026 Kenneth Stott
// Canary: e2d301b1-b1e4-4e72-88e1-c23763bbba10
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useId } from "react";

/**
 * What a control takes to be NAMED by its label's text alone and DESCRIBED by its help
 * (REQ-1968): the (?) sits inside the label, and without this its text would be read as part of
 * the control's name. `textId` goes on the element holding the label's text.
 */
export function useHelpNaming(help: string | undefined) {
  const textId = useId();
  return help === undefined
    ? { textId: undefined, naming: {} }
    : { textId, naming: { "aria-labelledby": textId, "aria-description": help } };
}
