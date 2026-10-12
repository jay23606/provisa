// Copyright (c) 2026 Kenneth Stott
// Canary: ce6565cd-a030-4c07-a59d-7ece353eb20b
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * How much room one cell of a page list may ask for. Set once, here, for every list.
 *
 * A column asks for no more width than its cap, so one long value cannot push the list past the
 * window; a row grows no taller than its maximum of lines. What does not fit is cut with an
 * ellipsis and shown whole on hover or focus.
 */
export const LIST_COLUMN_CAP_PX = 320;
export const LIST_ROW_MAX_LINES = 3;
/**
 * The narrowest a column of wrapped text is squeezed to, in characters: it gives up width to keep
 * the list inside the window, but never so much that it reads one word to a line. A phrase no
 * longer than this has no such minimum: it may wrap at its spaces down to its longest word.
 */
export const LIST_WRAP_MIN_CHARS = 24;
/**
 * The narrowest a column holding a long single value (an id, a host, a path) is squeezed to, in
 * characters: the value is already cut with an ellipsis, so it gives up width before the list
 * passes the window, keeping enough of its start to tell one value from another. A value no
 * longer than this keeps its whole width.
 */
export const LIST_CUT_MIN_CHARS = 12;
