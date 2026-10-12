# Node connector (REQ-1984)

Status: design for review. No product code has been written.

REQ-1984 is the spec. A Node source holds a bundle: JavaScript plus TypeScript declarations. Its exported functions are read by their JSDoc tags:

- `@table`: a table. Its parameters are the table's parameters; its return value is the rows.
- `@command`: a command.
- `@stream`: a live table. Its rows are delivered as they arrive.

The source names its runtime (Node, Bun or Deno) and its code (an npm package, a Git commit or tag, or an uploaded archive). Package registries are an organization setting.

The work has seven parts. Parts 1 to 4 do not depend on grpc-fix's work and come first. Parts 5 to 7 reuse REQ-1986 (parameters) and REQ-1980 (pipeline-table landing) and come after them.

| Part | What | Depends on |
|---|---|---|
| 1 | Package registries org setting | nothing |
| 2 | Install pipeline | 1 |
| 3 | Type reader | 2 |
| 4 | Worker | 2 |
| 5 | `@table` tables | 3, 4, REQ-1986, REQ-1980's landing branch |
| 6 | `@command` commands | 3, 4 |
| 7 | `@stream` live tables | 5 |

Section 12 lists the open decisions, which the maintainer has not made. Every statement below that goes beyond REQ-1984 is marked *(proposed)*.

## 1. What exists today

| Piece | Where | Used for |
|---|---|---|
| Org-wide list setting in the platform plane, credentials kept as entered and resolved at use | `org_mail_platforms` (`core/schema_admin.py:800`), `core/mail_platforms.py` (`put` :232, `resolved` :134), `api/admin/mail_platforms_router.py` | Part 1, copied in shape |
| The standard resolution of a field (`${secret:…}`, `${env:…}`, `${user:…}`), failing closed | `core/secrets.py:34,137` (`resolve_secrets`); vault bound per read with `secrets_store.bound` | Part 1, every registry field |
| Delete protection for a secret a stored value names | `core/secret_references.py:17-21,230` searches every text column of org-scoped platform tables | Part 1, nothing to register |
| Org settings admin tab, gated by `org_settings` held in that org | `App.tsx:550`, `AdminPage.tsx:84,488`, `navGroups.ts:211`, `MailPlatformsSection.tsx`, `secrets_router._org_guard` | Part 1 UI |
| Pinned, hash-verified download cache | `runtime_deps/pgwire_bundles.py` (`BundleResolver`, cache under `$PROVISA_RUNTIME_DEPS_CACHE`) | Part 2 cache layout; the runtimes themselves (section 8) |
| Archive upload with zip-bomb and path-traversal guards | `import_shared/upload.py:38-81,126` | Part 2 uploads |
| Git fetch with a URL resolved at use | `core/env_ci.py:108-180` (dulwich) | Part 2 Git |
| A per-source long-running process, started lazily, dying with its parent | `federation/pgwire_replica.py` (spawn :621, health :655, `endpoint()` :1079, `--owner-pid` :730, `stop_all_servers` from `api/app.py:3166`) | Part 4 lifecycle |
| Parameter columns, one required rule for every source kind | REQ-1986, in progress: `core/parameters.py` (`PARAMETER_KINDS`, `missing_parameters`, `is_required`), `native_filter_required`, `required_by_steward` | Part 5 |
| Rows landed in the engine per argument set before the statement runs | `api/data/materialization.py:850` (`_materialize_api_to_engine_cache`), `api_source/engine_cache.cache_table_name`; REQ-1980 adds the pipeline branch | Part 5 |
| Strict argument conversion and output-column validation | REQ-1980, to live in one module (grpc-fix: `mongodb/arguments.py` or a general one) | Parts 5 to 7 |
| Preview-then-register for tables whose columns come from a run | `api/admin/_neo4j_registration.py:28`, `neo4j/source.py:85` (`infer_columns`), `_query_api_registration.py:73` | Part 5 |
| Command model and dispatch | `core/models.py:1593` (`Function`), `executor/function_dispatch.py:500` (`_EXECUTORS`), `api/data/action_exec.py:234` (`invoke_command`), `security/mutation_authz.py:165` (`admit_command`) | Part 6 |
| Push sources: a listener per table landing rows by key; per-row SSE with governed read-back | `events/push_wiring.py:126,634`, `api/data/subscribe.py:370,451`, `live/governed.py:119`, `subscriptions/base.py:15` | Part 7 |
| Nested object types on a json column | `Column.object_fields` (`core/models.py:815,856`), `compiler/schema_inputs.py:54` (GraphQL), `compiler/context.py:186` (SQL paths) | Part 3, as a first step only (section 3.4) |

Facts that bear on the design:

- **No JavaScript runtime ships with Provisa.** The Docker image is `python:3.12-slim`, and the PyPI tier's policy says "No npm / Node" (`packaging/pypi/MIRROR-CHECKLIST.md:97`). Section 8 covers this.
- **No kept, hashed upload store exists.** The only kept upload is the org logo, stored as bytes without a hash. Part 2 needs one.
- **The IR has no array, struct or enum type** (`core/ir_types.py:36-57`). Nested values reach surfaces only as a `json` column with `object_fields`. That shape is one level deep for gRPC sources, has no named or shared types, and has no list-of-object type on GraphQL. Section 3.4 covers what "become types on every surface" needs.
- **No command kind keeps a worker.** `script` (`function_dispatch.py:58`) starts one process per call.

## 2. Model

### 2.1 The source

`SourceType.node`. The source row keeps one per-type configuration object *(proposed: in the per-type JSON the source store already keeps; to confirm against `provisa_sources` during part 2)*:

| Field | Meaning |
|---|---|
| `runtime` | `node`, `bun` or `deno` |
| `code.kind` | `npm`, `git` or `upload` |
| `code.package`, `code.version` | npm: the package name and an exact version. A range or tag is refused at save. |
| `code.repository`, `code.ref`, `code.subdirectory` | Git: the repository URL, a commit or tag, and the bundle's directory within it |
| `code.upload` | upload: the stored archive's content hash |
| `code.commit` | Git: the commit the ref named when it was pinned *(proposed: a tag is resolved to its commit at save, and the commit is what is fetched)* |
| `content_hash` | The SHA-256 of the bundle's content, recorded at save (section 4.2) |
| `manifest` | What the type reader found (section 3.3), recorded at save |

The source has no credential field. Credentials come from the org's package registries (part 1).

### 2.2 Tables, commands and live tables

These are the existing models, with nothing new except the values listed here.

- **`@table`**: a registered table. Its `source_id` is the Node source and its `table_name` is the export's name.
  - Each function parameter is a REQ-1986 parameter column named `_nf_<name>`, with `native_filter_type = "node_arg"`. This is a new value in `PARAMETER_KINDS`, which REQ-1986's text would list next to `pipeline_arg`.
  - `native_filter_required` is true for a non-optional parameter, and false for an optional one, which the steward can make required with `required_by_steward`.
  - The data columns come from the return type, or from a preview (section 5.2).
  - The table description is the JSDoc text.
- **`@command`**: a `Function` with a new `impl_kind = "node"` and `binding = {"source_id", "export"}`. Its `arguments` come from the parameters and its `output_columns` from the return type. The description is the JSDoc text.
- **`@stream`**: a registered table with the same parameter and column rules as `@table`, marked as a stream *(proposed: by its source type and the manifest entry's tag, as push tables are marked by source type today; no new column)*.

## 3. Type reader (part 3)

### 3.1 What it reads

The reader reads the bundle's TypeScript declarations only. It never reads the bundle's JavaScript and never runs the bundle.

- The entry declaration file is the package's `types` (or `typings`) field, else `index.d.ts`. A bundle with neither is refused when it is loaded.
- A JavaScript bundle typed with JSDoc ships declarations generated from it (`tsc --allowJs --declaration`). This is the form REQ-1984 states: "A bundle is JavaScript plus TypeScript declarations carrying the tags".

### 3.2 How it runs

Provisa ships the reader as one pre-bundled JavaScript file containing the TypeScript compiler API at a pinned version (*proposed: `provisa/node/reader.mjs`, built when Provisa is built*). It runs under the source's own runtime, so a source needs no runtime other than the one it names. The reader prints one JSON manifest. Python reads the manifest; it does not parse TypeScript.

### 3.3 Manifest

```json
{
  "exports": [
    {"name": "orders_by_customer", "tag": "table", "description": "…",
     "parameters": [{"name": "customerId", "optional": false, "type": {"ref": "CustomerId"}}],
     "returns": {"collection": "async_iterable", "element": {"ref": "Order"}}}
  ],
  "types": {"Order": {"kind": "object", "fields": [{"name": "id", "type": {"scalar": "text"}, "optional": false}]}},
  "problems": [{"export": "x", "type": "Foo", "reason": "…"}]
}
```

The rules REQ-1984 states, applied by the reader:

- **Untagged exports** are ignored.
- **Unknown tags.** A tag other than `@table`, `@command` or `@stream` on an export is a problem naming the export and the tag.
- **`@table` returns a collection.** The return type must be an array or an iterable (`T[]`, `Array`, `ReadonlyArray`, `Iterable`, `AsyncIterable`, `Generator`, `AsyncGenerator`), alone or inside a `Promise`. A function that returns a single object is a problem naming it.
- **`@stream` is an async generator.** The return type must be `AsyncGenerator<T>` or `AsyncIterable<T>`. A declaration file shows only the return type, so the reader cannot tell an `async function*` from a function that returns an async iterable. Both are accepted.
- **Referenced types.** Every type a tagged function refers to (its parameters, its return type and every type they reference) is entered in `types`. A type that cannot be mapped is a problem naming it.

The bundle is refused when it is loaded if `problems` is not empty. The refusal lists every problem by name.

### 3.4 Type mapping

| TypeScript | Maps to |
|---|---|
| `string` | `text` |
| `number` | `double` *(proposed; see open decision 6)* |
| `bigint` | `bigint` |
| `boolean` | `boolean` |
| `Date` | `timestamp` |
| `T \| null`, `T \| undefined`, an optional property | `T`, nullable |
| `T[]`, `Array<T>`, `ReadonlyArray<T>` | a list of `T` |
| interface, object type alias, class instance type | a named object type with its fields |
| a union of string literals | an enum |
| `Record<string, T>`, `{[k: string]: T}` | `json` *(proposed)* |
| `any`, `unknown` | `json` *(proposed; see open decision 6)* |
| other unions, functions, symbols, tuples, recursive types | cannot be mapped |

"Become types on every surface" is more than today's surfaces can show. Today a nested value is a `json` column with per-column `object_fields`. That gives one object type per column, no list of objects, no enum, no shared type names, and a JSON string on gRPC. Open decision 1 asks how far this connector takes it.

### 3.5 Columns versus types

REQ-1984 says columns come "from the function's TypeScript return type, or a preview when the type cannot be mapped". It also says "a type that cannot be mapped is refused by name when the bundle is loaded". Read together, these overlap: the preview is only reachable for a return type the reader cannot map, and that same type is refused when the bundle loads. Open decision 2 asks which one wins for a `@table` element type.

Until that is decided, this design reads it this way:
- The element type's own fields become the columns when the element type can be mapped.
- A function whose element type is `any`, `unknown` or `Record<…>` is typed by a preview.
- Any other type that cannot be mapped is refused.

## 4. Install pipeline (part 2)

### 4.1 Getting the code

| Kind | How | Pinned by |
|---|---|---|
| npm | `npm pack <package>@<version>` in an isolated directory, through the org's npm registries (section 6) | the exact version, and the tarball's registry integrity (`sha512`) checked against the one recorded at save |
| Git | dulwich fetch of the recorded commit through the org's Git hosts; the subdirectory is the bundle | the commit |
| upload | the archive from the upload store, checked with the `import_shared/upload.py` guards | its content hash |

### 4.2 Content hash

The content hash is the SHA-256 over the bundle's files, in sorted path order, with each path and its bytes, *before* any install. It is recorded at save. A later load that finds different content refuses to run the source and names the source and both hashes.

### 4.3 Dependencies

The bundle must carry a lockfile the runtime reads (`package-lock.json`, `npm-shrinkwrap.json`, `bun.lock`, `bun.lockb` or `deno.lock`), unless it is a single pre-bundled file, which needs no install. Dependencies are installed in the runtime's frozen-lockfile mode:

| Runtime | Command |
|---|---|
| Node | `npm ci` |
| Bun | `bun install --frozen-lockfile` |
| Deno | `deno install --frozen` |

A lockfile out of step with `package.json` fails the install, and the failure names the source.

Install scripts (`preinstall`, `postinstall`) are not decided; see open decision 4.

### 4.4 When, and where it is kept

- **When.** Installation happens when the bundle is loaded: at save, at boot, and on the first use in a process that has not loaded it. It never happens per call.
- **Where.** The cache directory is `<cache>/node/<runtime>/<content_hash>/`, written to a temporary directory and renamed into place when complete, so a half-finished install is never used. *(proposed: the cache root is the `runtime_deps` cache root.)*
- **Fleet.** Each host installs for itself from the pinned reference, and the content hash makes every host's copy the same.

### 4.5 Uploads

There is no kept, hashed upload store today. *(proposed: an `org_node_bundles` table in the platform plane, keyed by `(org_id, content_hash)` and holding the archive's bytes. Deleting a source does not delete its archive while another source names it. Open decision 5.)*

## 5. `@table` tables (part 5, after REQ-1986)

### 5.1 Registration

Discovery offers each `@table` export as a table to register, as other API-style sources do. Nothing is registered until a steward registers it.

Registration writes:
- one parameter column per function parameter (section 2.2);
- the data columns;
- the JSDoc description.

The REQ-1986 rules then apply unchanged:
- A source-required parameter is locked.
- A steward may make an optional parameter required.
- The table page's Parameters section shows each parameter.
- The one check, `parameters.missing_parameters`, refuses a read missing a required parameter before anything is sent. It runs ahead of every per-kind branch in `_materialize_api_to_engine_cache`, so the Node branch is covered without code of its own.

### 5.2 Columns

- **From the type.** Each top-level field of the element type is a column, with nested types as in section 3.4.
- **From a preview.** When open decision 2 allows it, the function is called once in the worker with sample arguments. Up to five rows are returned, and columns are inferred as `neo4j/source.py:infer_columns` does. The form refuses to submit until the columns are typed. The sample arguments are not stored.

### 5.3 Reading

- **Routing.** A Node table is landed, never read in place. `node` joins `_MATERIALIZE_ONLY` (`federation/strategy.py:84`) and `_ADAPTER_FETCH_ONLY` (`events/source_loader.py:41`), and routes as a pipeline table does.
- **The branch.** One new branch in `_materialize_api_to_engine_cache`, plus the same lookup in `would_materialize_optimize`. It:
  1. converts each argument strictly with REQ-1980's converter, refusing a value that does not convert by naming the table, the parameter and the type;
  2. calls the export in the worker (section 7);
  3. validates each row against the columns with REQ-1980's output validation;
  4. lands the rows with `land_api_cache` under `cache_table_name(source_id, "node:" + table_name, args)` and the table's `cache_ttl`.
- **Argument order.** Parameters are passed to the function in declared order. An absent optional parameter is passed as `undefined`, so the function's own default applies.
- **No-parameter tables.** A table with no parameters has a constant key. It behaves as a view with a TTL and is replicable, as a no-argument pipeline table is.

### 5.4 Governance and surfaces

A Node table is a registered table: visibility, masks, row rules and domains apply to the landed rows, and parameter columns are not data. It is served on every surface a pipeline table is (GraphQL field arguments, SQL `_nf_` conditions, and the rest). REQ-1980's test plan covers each surface, and this one copies it.

## 6. Package registries (part 1)

### 6.1 Model

*(proposed)* An `org_package_registries` table in the platform plane, keyed by `org_id`, in the shape of `org_mail_platforms`. It is one per organization and outside every environment, as REQ-1984 says: "an organization setting".

| Column | npm registry | Git host |
|---|---|---|
| `id` | yes | yes |
| `kind` | `npm` | `git` |
| `url` / `host` | the registry URL | the host |
| `scope` | optional, e.g. `@acme` | — |
| `credential` | the token | the token *(proposed: HTTPS only; open decision 3)* |
| `mirror` | at most one npm row is the mirror | — |

Every field holds what was entered, so a value can be a secret reference (`${secret:npm_token}`). Nothing is written to a vault and no secret name is made up. Delete protection for a referenced secret already covers platform tables with nothing to register.

### 6.2 API and page

- **API.** `GET`, `PUT` and `DELETE` on `/admin/orgs/{org_id}/package-registries`, guarded as Mail Platforms is: `org_settings` held in that organization. `cross_org` and `platform_settings` do not open it.
- **Page.** A Package registries tab on the organization settings page, built from the Mail Platforms section, with `FormLayout`. It has two lists, npm registries and Git hosts, and the mirror is a checkbox on an npm row.

### 6.3 Use

Every install resolves the rows with the standard resolution, with the org vault bound for that install only (`mail_platforms.resolved` is the model). It then writes the runtime's configuration into the install's isolated directory:

| Runtime | Configuration |
|---|---|
| Node | `.npmrc` with `registry=`, `@scope:registry=` and `//host/:_authToken=` |
| Bun | `bunfig.toml` with the same entries |
| Deno | `DENO_AUTH_TOKENS` in the install's environment, and an `.npmrc` for npm specifiers |

- **The mirror.** When an npm row is the mirror, it is the default registry, and every unscoped package goes through it.
- **Git.** Git hosts supply the credential for a Git source's fetch, and for Git dependencies in a lockfile.
- **Cleanup.** The configuration is removed when the install ends, whether it succeeded or failed. The cache keeps no configuration, and the worker's environment has no credential.
- **The public npm registry** needs no row.

## 7. Worker (part 4)

- **One per bundle per Provisa process.** A long-running process runs per `(source, content_hash)` in each Provisa process, in the source's runtime, started from the installed cache directory. *(proposed: per process, not per host; open decision 7.)*
- **Host script.** Provisa ships a small host script, the same one for every runtime (*proposed: `provisa/node/host.mjs`*). It imports the bundle's entry and serves calls. The bundle imports nothing of Provisa's.
- **Lifecycle.** The lifecycle copies `pgwire_replica`:
  - The worker starts lazily on first use.
  - It is spawned in its own session with `--owner-pid`, so it dies with its parent.
  - It is health-checked by a ping on the socket.
  - A worker that has exited is dropped, so the next call starts a new one. There is no restart loop.
  - It stops when its source is edited or deleted, and when the app shuts down.
- **Protocol.** A Unix domain socket in a private directory (mode 0700). Messages are length-prefixed JSON, multiplexed by call id:

  | Message | From | Purpose |
  |---|---|---|
  | `call {id, export, kind, args}` | Provisa | `kind` is `table`, `command` or `stream` |
  | `rows {id, rows}` | worker | a batch of rows |
  | `end {id}` | worker | the call is complete |
  | `error {id, message, stack}` | worker | the call failed |
  | `cancel {id}` | Provisa | stop the call |
  | `ping` / `pong` | both | health check |

- **Iteration.** The host iterates arrays and sync or async iterables in batches.
- **Deadlines.** A call registers with the request deadline (`request_deadline.cancel_on_deadline`), so a cancelled request sends `cancel`. The host then calls `return()` on the iterator.
- **Failures.** A worker crash fails every call in flight with an error naming the source and the export.
- **Runtime command lines.** `node host.mjs`, `bun host.mjs` and `deno run host.mjs`. Deno's permission flags are not decided (REQ-1984 leaves them open).

## 8. Shipping the runtimes

Provisa ships no JavaScript runtime today, and the PyPI tier forbids one. *(proposed: Node, Bun and Deno are fetched on demand at pinned versions with recorded hashes, through a `runtime_deps` resolver beside `pgwire_bundles.py`. The Docker image, AppImage, macOS, Windows and NixOS packages would then need no runtime of their own. The PyPI policy line changes from "no Node" to "no Node in the wheel".)* Open decision 8.

## 9. `@command` and `@stream`

### 9.1 `@command` (part 6)

- **Execution.** A new executor in `_EXECUTORS`, `impl_kind = "node"`, calls the export in the worker.
- **Arguments** are converted as in section 5.3.
- **Output.** A collection return gives rows; a single object gives one row; `void` gives none. Each is checked against `output_columns`.
- **Everything else is the existing command path:** `invoke_command`, `admit_command`, approval, audit, and every command surface.
- **Query or mutation.** A command's `kind` must be one or the other, and REQ-1984 does not say which. Open decision 9.

### 9.2 `@stream` live tables (part 7)

- **Where rows arrive.** The surfaces that serve subscriptions are per-row SSE (`/data/subscribe/{table}`), GraphQL subscriptions over SSE, and the Kafka sink. REQ-1984 says "each row it yields is delivered as it arrives". That matches the per-row SSE path. GraphQL subscriptions send a snapshot per change, not single rows.
- **How governance applies today.** Pushed rows are landed by key, and each subscriber's rows are read back by primary key through governance (`live/governed.py`), so row rules and masks apply. That path assumes one shared stream per table and a primary key.
- **Why a stream is different.** A Node stream has parameters, so there is one generator per subscriber's argument set, and its rows need not have a key.
- **Open decision 10** asks how stream rows are governed and delivered. *(proposed: one generator per distinct argument set, shared by every subscriber with those arguments. Each row is appended to a landed table keyed by the argument set, and delivered to each subscriber through the governed read of the rows just appended. A stream with no parameters is one shared generator.)*

## 10. Sequence

1. **Part 1** (registries setting) and the upload store.
2. **Part 2** (installer) and the runtime resolver.
3. **Part 3** (reader) and **part 4** (worker), in parallel.
4. **Part 5** (`@table`), after REQ-1986 has landed and REQ-1980's landing branch and converter exist. If REQ-1980 lands later, the Node branch waits for its converter rather than building one.
5. **Part 6** (`@command`).
6. **Part 7** (`@stream`), after open decision 10.

Each part ships when it passes its own gate. The docs and the source-type counts (`docs/sources.md`, the tour's count, the source picker) are updated with part 5, when the first Node table can be registered.

## 11. Tests

**Unit** (`tests/unit`, no container, no network):
- Reader: fixture declaration files for every row of the mapping table, every refusal (unknown tag, single-object `@table`, unmappable type, missing declarations), and JSDoc descriptions. These need the pinned reader and one runtime on the unit lane; open decision 8 decides how the lane gets it.
- Content hash: stable across file order, and changed by any byte.
- Registries: as-entered storage, resolution at use, one mirror at most, the guard, and the configuration files written and removed (including on a failed install).
- Worker protocol: framing, multiplexing, cancel on deadline, and a crash failing the calls in flight. These use a stub worker that speaks the protocol.
- Parameters and landing: `node_arg` in `PARAMETER_KINDS`, `native_filter_required` from optionality, the cache key per argument set, and `would_materialize_optimize` agreeing with the branch.

**Integration and e2e** (CI only, never run locally). An isolated compose project on unique, unexposed ports, with a private npm registry (Verdaccio) and a Git server. For each runtime:
- an npm source through a scoped private registry, and through the mirror;
- a Git source at a tag;
- an uploaded archive;
- a `@table` with a required and an optional parameter, joined in SQL to a Postgres table;
- the same table over GraphQL;
- a missing required parameter, refused;
- a mask and a row rule on Node rows;
- a `@command`;
- a `@stream` subscribed over per-row SSE;
- a changed lockfile refused by the frozen install;
- a changed archive refused by the content hash.

UI: the Package registries tab, and the Register Table form on a Node source.

## 12. Open decisions

1. **How far "types on every surface" goes.** Today's `object_fields` gives per-column object types on GraphQL and SQL paths, and a JSON string on gRPC. Named shared types, lists of objects, enums, and proto messages are new work on every surface.
   - Recommended: build them as a named-type registry per source that GraphQL, gRPC and the SQL catalog read, and start with GraphQL and gRPC.
   - The maintainer's call, because it is the largest part of this work.
2. **Preview versus refusal for an element type that cannot be mapped** (section 3.5). Recommended: preview only for `any`, `unknown` and `Record`; refuse every other unmappable type.
3. **Git credentials.** Recommended: HTTPS tokens only. SSH deploy keys need key files on disk and a known-hosts policy.
4. **Install scripts.** Recommended: `--ignore-scripts` for every install. A dependency's `postinstall` would otherwise run arbitrary code at install time, with the install's credentials present.
5. **Upload store.** Recommended: a platform-plane table keyed by content hash. The alternative is the object store, which a native deployment does not have.
6. **`number`, `any` and `unknown`.** Recommended: `number` maps to `double`, and `any` and `unknown` map to `json`. Mapping `number` to an integer would need a tag REQ-1984 does not define.
7. **Worker scope.** Recommended: one worker per Provisa process. One per host would need a lock and shared sockets across worker processes.
8. **Shipping the runtimes** (section 8). Recommended: fetch on demand, pinned and hashed.
9. **A command's kind.** Recommended: `mutation`, with the steward able to set `query` when registering it.
10. **Stream delivery and governance** (section 9.2). Recommended: one shared generator per argument set, landed and read back through governance.
11. **Isolation of user code.** A bundle runs with the Provisa process's network and filesystem reach, and the egress allow-list (`function_dispatch.py:317`) does not cover it. Deno's permissions are undecided in REQ-1984. Recommended: decided with open decision 4 before part 4 ships. This is a security decision.
