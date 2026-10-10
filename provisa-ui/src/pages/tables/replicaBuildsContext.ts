// Copyright (c) 2026 Kenneth Stott
// Canary: 61b3e4f0-dd6b-4569-b63a-c1bb29cc7d38
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The replica builds the table list last read from the server, for what it shows inside a
// table's detail (the table form's build line): one request serves the list and the detail.
// Null where builds are not known -- not read yet, or the caller may not read them.

import { createContext } from "react";
import type { ReplicaBuilds } from "../../api/admin";

export const ReplicaBuildsContext = createContext<ReplicaBuilds | null>(null);
