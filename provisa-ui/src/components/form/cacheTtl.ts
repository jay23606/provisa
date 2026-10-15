// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A Cache TTL is seconds, 0 or more, or -1: never expires -- the table lands once, is always
// read from its replica, and its source is not asked again.

import type { TFunction } from "i18next";

export const NEVER_EXPIRES = -1;

/** A TTL in words: "300s", or "never expires" for -1. */
export function ttlText(ttl: number, t: TFunction): string {
  return ttl === NEVER_EXPIRES ? t("cacheTtl.neverExpires") : `${ttl}s`;
}

/** The hint beneath a Cache TTL editor holding `value`: what -1 means, or that -1 is allowed. */
export function cacheTtlHint(value: number | string | null | undefined, t: TFunction): string {
  return Number(value) === NEVER_EXPIRES && value !== "" && value != null
    ? t("cacheTtl.neverExpiresHint")
    : t("cacheTtl.inputHint");
}
