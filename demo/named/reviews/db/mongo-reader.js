// Copyright (c) 2026 Kenneth Stott
// Canary: 6cf4af76-30bb-45a4-815b-de01c7813908
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.
//
// The reader Provisa connects as (config.yaml catalog): it reads every database and writes none.
// Run once, when the store first starts (docker-entrypoint-initdb.d), in both compose files.
db.getSiblingDB("admin").createUser({
  user: "reviews_reader",
  pwd: "reviews_reader",
  roles: [{ role: "readAnyDatabase", db: "admin" }],
});
