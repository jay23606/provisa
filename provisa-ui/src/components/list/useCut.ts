// Copyright (c) 2026 Kenneth Stott
// Canary: 355f0fb5-18ae-4fdb-8d38-5d454d7b740f
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

import { useLayoutEffect, useState } from "react";

/** Whether an element shows less than it holds: cut at the side or at the foot. */
function isCut(el: HTMLElement): boolean {
  return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
}

/**
 * Follows an element's size and says whether it is cut. The element is followed through a callback
 * ref, not a ref object: a hint that opens on a cut value wraps its target anew, which mounts a new
 * element, and the measure moves to that one instead of watching the one that left the page.
 */
export function useCut<T extends HTMLElement = HTMLDivElement>(text: string) {
  const [el, ref] = useState<T | null>(null);
  const [cut, setCut] = useState(false);
  useLayoutEffect(() => {
    if (!el) return;
    const measure = () => setCut(isCut(el));
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    return () => watch.disconnect();
  }, [el, text]);
  return { ref, cut };
}
