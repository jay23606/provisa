// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1984, REQ-1993: a code source -- the organisation's own Node or Python functions, run in a
// sandboxed worker -- keeps what its code is in its mapping (provisa/codesource/source.py):
//
//   runtime   node | bun | deno (Node); python (Python)
//   code      a package at an exact version, a Git repository at a commit, or an uploaded archive
//   lockfile  a lockfile given beside a package reference (a published package carries none)
//   entry     a Python source's entry module, when its code has more than one
//
// The content hash of the code is pinned by the server when the source is saved.

export const NODE = "node";
export const PYTHON = "python";
export const CODE_SOURCE_TYPES = new Set([NODE, PYTHON]);

export const NODE_RUNTIMES = ["node", "bun", "deno"] as const;

/** Where the code comes from: a package (npm or PyPI), a Git repository, or an upload. */
export type CodeOrigin = "package" | "git" | "upload";

/** The package kind each language's packages come from. */
export const PACKAGE_KIND: Record<string, string> = { [NODE]: "npm", [PYTHON]: "pypi" };

/** The lockfiles each language installs from (provisa/node/install.py, provisa/python/install.py). */
export const LOCKFILES: Record<string, string[]> = {
  [NODE]: ["package-lock.json", "npm-shrinkwrap.json", "bun.lock", "bun.lockb", "deno.lock"],
  [PYTHON]: ["uv.lock", "pylock.toml", "requirements.txt"],
};

const COMMIT = /^[0-9a-f]{40}$/;

/** The source's mapping, as the server stores it, from the form's fields. */
export function codeMappingJson(type: string, fields: Record<string, string>): string {
  const origin = (fields.code_origin ?? "package") as CodeOrigin;
  const code =
    origin === "package"
      ? {
          kind: PACKAGE_KIND[type],
          package: (fields.code_package ?? "").trim(),
          version: (fields.code_version ?? "").trim(),
        }
      : origin === "git"
        ? {
            kind: "git",
            repository: (fields.code_repository ?? "").trim(),
            commit: (fields.code_commit ?? "").trim(),
            subdirectory: (fields.code_subdirectory ?? "").trim(),
          }
        : { kind: "upload", upload: fields.code_upload ?? "" };
  const lockfile =
    origin === "package" && fields.lockfile_upload
      ? { filename: fields.lockfile_filename, upload: fields.lockfile_upload }
      : null;
  const entry = (fields.code_entry ?? "").trim();
  return JSON.stringify({
    runtime: type === PYTHON ? PYTHON : (fields.code_runtime ?? "node"),
    code,
    ...(lockfile ? { lockfile } : {}),
    ...(type === PYTHON && entry ? { entry } : {}),
  });
}

/** The form's fields from a stored mapping. */
export function codeFieldsFromMapping(mappingJson: string): Record<string, string> {
  const m = JSON.parse(mappingJson) as {
    runtime?: string;
    code?: Record<string, string>;
    lockfile?: { filename: string; upload: string } | null;
    entry?: string;
  };
  const code = m.code ?? {};
  const origin: CodeOrigin =
    code.kind === "git" ? "git" : code.kind === "upload" ? "upload" : "package";
  return {
    code_runtime: m.runtime ?? "node",
    code_origin: origin,
    code_package: code.package ?? "",
    code_version: code.version ?? "",
    code_repository: code.repository ?? "",
    code_commit: code.commit ?? "",
    code_subdirectory: code.subdirectory ?? "",
    code_upload: code.upload ?? "",
    code_upload_filename: "",
    lockfile_upload: m.lockfile?.upload ?? "",
    lockfile_filename: m.lockfile?.filename ?? "",
    code_entry: m.entry ?? "",
  };
}

/** The fields the form cannot be saved without, by the field's key. */
export function missingCodeFields(fields: Record<string, string>): string[] {
  const origin = (fields.code_origin ?? "package") as CodeOrigin;
  const needed =
    origin === "package"
      ? ["code_package", "code_version"]
      : origin === "git"
        ? ["code_repository", "code_commit"]
        : ["code_upload"];
  const missing = needed.filter((k) => !(fields[k] ?? "").trim());
  if (origin === "git" && fields.code_commit && !COMMIT.test(fields.code_commit.trim())) {
    missing.push("code_commit");
  }
  return missing;
}
