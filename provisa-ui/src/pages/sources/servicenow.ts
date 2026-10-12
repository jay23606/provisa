// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1954: a ServiceNow source — the instance's address and the credential entered for it,
// riding in the source's host, username and password.

/** Whether an instance URL is one the server takes: the full https:// address, or a
 * ${secret:…} / ${env:…} reference to it (checked when the source is used). */
export function servicenowInstanceUrlValid(url: string): boolean {
  const value = url.trim();
  return value.startsWith("${") || /^https:\/\/\S+$/.test(value);
}
