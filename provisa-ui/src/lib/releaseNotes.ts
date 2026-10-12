// Copyright (c) 2026 Kenneth Stott
// Canary: b2fa80ff-4014-4e51-96ce-b0bcee656c6d
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The notes of the release this UI was built with. scripts/gen_release_notes.py writes them and
// the build bundles them, so reading them asks the server nothing. A release before the first one
// the notes show has none: the file then holds null.

import bundled from "../generated/releaseNotes.json";

export interface ReleaseNotes {
  version: string;
  previous: string;
  date: string;
  features: { category: string; entries: { text: string; changes: string[] }[] }[];
  changes: { scope: string; entries: string[] }[];
}

export const RELEASE_NOTES = bundled as ReleaseNotes | null;
