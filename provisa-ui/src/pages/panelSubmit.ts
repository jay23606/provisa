// Copyright (c) 2026 Kenneth Stott
// Canary: f1925a9b-bb48-47c4-9a30-3a3b188beb51
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * A panel's Save sits in the panel's head, outside the form it saves, so it cannot be the form's
 * own submit button. Pressing it asks the form to submit itself: the browser's required-field
 * checks run and the form's `onSubmit` is called, exactly as for a button inside it.
 */
export const submitForm = (id: string) => () =>
  (document.getElementById(id) as HTMLFormElement).requestSubmit();
