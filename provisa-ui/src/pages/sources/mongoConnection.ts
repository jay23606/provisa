// Copyright (c) 2026 Kenneth Stott
// Canary: d0f0eae0-b65f-4986-8439-3f019642a1ca
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/** Whether a MongoDB source's host is a connection string rather than a host name (REQ-1985). */
export function isMongoConnectionString(host: string): boolean {
  return host.startsWith("mongodb://") || host.startsWith("mongodb+srv://");
}
