// Copyright (c) 2026 Kenneth Stott
// Canary: 2c8f5a17-9e43-4b06-b1d7-6a0e3f9c4d58
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useEffect, useMemo, useRef } from "react";
import type { ClusterLevel } from "./graph-clusters";
import type { FrameView } from "./graph-model";

/** A frame's requested view (Polly's navigate, an in-app link): its group-by is the frame's own
 *  Group by control, set once per request; its layout and collapse are the canvas's, returned to
 *  hand to it. Once applied, the viewer's own changes stand. */
export function useRequestedView(
  requestedView: FrameView | undefined,
  setClusterLevel: (level: ClusterLevel) => void,
) {
  const groupedForSeqRef = useRef<number | null>(null);
  useEffect(() => {
    if (!requestedView || requestedView.groupBy === undefined) return;
    if (groupedForSeqRef.current === requestedView.seq) return;
    groupedForSeqRef.current = requestedView.seq;
    setClusterLevel(requestedView.groupBy ?? "none");
  }, [requestedView, setClusterLevel]);
  return useMemo(
    () =>
      requestedView && {
        layout: requestedView.layout,
        collapseGroups: requestedView.collapseGroups,
        seq: requestedView.seq,
      },
    [requestedView],
  );
}
