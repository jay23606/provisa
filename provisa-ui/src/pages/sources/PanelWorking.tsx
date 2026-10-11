// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A working surface opened from an item of a list -- schema discovery, a table mapping, a test
// run -- shown in the list's detail panel in place of the item, with a way back to it, as the
// Tables page does for a table's preview.

import type { ReactNode } from "react";
import { Button } from "@mantine/core";
import { ArrowLeft } from "lucide-react";

export function PanelWorking({
  back,
  onBack,
  testId,
  children,
}: {
  /** What the way back says: where it leads. */
  back: string;
  onBack: () => void;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="split-pane__fill">
      <div className="split-pane__bar">
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<ArrowLeft size={14} />}
          onClick={onBack}
          data-testid={testId}
        >
          {back}
        </Button>
      </div>
      {children}
    </div>
  );
}
