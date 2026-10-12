# Code sources: one worker protocol, Node and Python (REQ-1984, REQ-1993)

Status: design approved by the lead on 2026-10-12, decisions in section 9. Node parts 1 to 3 are built; the rest follows section 7.

A code source is a source whose tables, commands and live tables are functions in code the organisation wrote. Node (REQ-1984) is the first; Python (REQ-1993) is the second. This note is the part both share, and the Python half. The Node note (docs/arch/node-connector.md) stays the Node half, and its sections 4, 5 and 7 move here where they are shared.

Every statement below that goes beyond REQ-1984 or REQ-1993 is marked *(proposed)*; the lead approved them with this design.

## 1. What is shared and what is per language

| Concern | Shared | Per language |
|---|---|---|
| The model of what code offers: exports, parameters, row types, named types, problems by name | `provisa/codesource/manifest.py` (today `provisa/node/manifest.py`, moved) | — |
| How a declaration says what it offers | — | Node: JSDoc tags and TypeScript declarations. Python: docstring tags and type hints |
| The type reader | its output format and rules (section 2) | the program that reads: `reader.mjs` (TypeScript compiler) / `reader.py` (section 6.2) |
| Content hash, uploads, Git fetch, the cache layout | `provisa/codesource/bundle.py`, `uploads.py`, `git.py` (today in `provisa/node/`, moved) | — |
| Package fetch and dependency install | the cache-by-hash and isolated-configuration rules | npm + lockfile (built) / PyPI + lockfile (section 6.3) |
| Runtimes, fetched pinned and hashed | the resolver (`runtime_deps/js_runtimes.py`, renamed `code_runtimes.py`) | the pins: Node, Bun, Deno / CPython (python-build-standalone) and uv |
| Organisation package settings | the admin page and its resolution (built for npm and Git) | a PyPI index kind (section 6.4) |
| The worker: process, socket, frames, messages, cancel, crash, pool | `provisa/codesource/worker.py` (section 3) | the host program: `host.mjs` / `host.py` |
| The sandbox | its rules and the OS mechanism (section 4) | Deno's own flags; everything else uses the OS sandbox |
| Tables, commands, live tables, parameters, landing, governance | parts 5 to 7 (REQ-1986, REQ-1980), unchanged | — |
| Source type | — | `SourceType.node`, `SourceType.python` |

Nothing in the shared layer names a language. A language is a `CodeLanguage` *(proposed)*: its source type, its runtimes, its reader command, its host command, its package fetch and install, and its lockfiles.

## 2. The reader's output (the manifest's input)

Each language's reader prints one JSON document, the same for both:

- `exports`: name, tags, description, signatures (parameters: name, optional, rest, type; returns: type);
- `types`: named object types with fields;
- `diagnostics`: the language's own errors in the declarations.

Types are the trees Node's reader already writes: `string`, `number`, `bigint`, `boolean`, `date`, `literal`, `union`, `array`, `object`, `ref`, `record`, `any`, `unknown`, `promise`, `iterable` (async, generator), `undefined`, `null`, `unsupported`.

Python's reader writes the same trees. Its mapping (section 6.2) adds two values the tree already has room for: `int` is written as `number` with `integer: true`, so it maps to `bigint` rather than `double` *(proposed: a Python int is an integer; Node's number stays double)*, and `Decimal` as `decimal`, which maps to numeric and travels as a string on the wire (decision P5). Node has no decimal type, so its reader never writes one.

The rules in `manifest.read_manifest` apply unchanged to both languages: which exports are tables, commands and streams; a table returns a collection; a stream is an async generator (for Python, a generator or an async generator, per REQ-1993); columns from the row type or a preview for a loose row; every referenced type mapped; every problem by name, all at once.

## 3. The worker protocol

One long-running process per code source per Provisa process, in its runtime, started from the installed cache directory.

- **Transport:** a Unix domain socket in a private directory (mode 0700). Provisa listens; the host connects. A socket, not the process's stdout, so anything the code prints never reaches the protocol.
- **Frames:** a 4-byte big-endian length, then UTF-8 JSON.
- **Values:** JSON, with a timestamp as `{"$date": iso}`, a big integer as `{"$bigint": digits}`, a decimal as `{"$decimal": digits}`, a missing value as null.
- **Messages:**

  | From | Message | Meaning |
  |---|---|---|
  | host | `hello {exports}` | the host loaded the code; these are its exports |
  | Provisa | `call {id, export, kind, args}` | `kind` is table, command or stream; `args` in declared order |
  | host | `rows {id, rows}` | a batch (tables: up to 1000; streams: each row as it is yielded) |
  | host | `value {id, value}` | a command's single result |
  | host | `end {id}` / `error {id, message, stack}` | the call finished / failed |
  | Provisa | `cancel {id}` | stop the call; the host closes the iterator or generator |
  | either | `ping` / `pong` | health |

- **Lifecycle:** as Node's note section 7 has it. The process is started lazily, health is a ping, one that has exited is dropped so the next call starts another, it is stopped when its source is edited or deleted and when the app shuts down, and it exits when its socket closes.
- **Calls:** multiplexed by id; a request's deadline sends `cancel`; a crash fails every call in flight, naming the source and the export.
- **Pool:** keyed by `(source, content hash)`.

`host.mjs` (Node part 4) implements this. `host.py` *(proposed)* is the same program in Python, built on asyncio: it imports the code's module, says hello, and serves calls, iterating sync and async generators and lists alike.

## 4. The sandbox, for every runtime

The maintainer's ruling for Node applies to Python (REQ-1993): no file access beyond the code, and network only to the egress allow-list.

- **Deno:** its own permissions, `--allow-read` (the bundle and the socket directory), `--allow-write` (the socket only) and `--allow-net=<allow-list hosts>`.
- **Everything else** (Node, Bun, Python):
  - **Files:** the OS sandbox gives the process read access to its installed code directory, its runtime directory and the socket directory, and nothing else.
  - **Network:** the egress allow-list names hosts, and no OS sandbox filters by host name. So the process may connect only to the socket and to a local proxy Provisa runs, and the proxy admits a connection only to a host on the allow-list (HTTP CONNECT for TLS, and plain HTTP by host). The runtime is pointed at it: `HTTP_PROXY` and `HTTPS_PROXY` for every runtime, plus `NODE_USE_ENV_PROXY=1` for Node 24, whose built-in fetch otherwise ignores them. A program that opens a raw socket to any other address is refused by the OS sandbox, not by the proxy.
  - **Mechanism** *(proposed)*:
    - macOS: `sandbox-exec` with a generated profile (`deny default`; read the listed directories; outbound only to `localhost` on the proxy's port; the Unix socket);
    - Linux: `bwrap` (bubblewrap) with the listed directories bound read-only, a fresh network namespace, and the proxy reached through a Unix socket bound into it *(the proxy listens on a Unix socket, and a small forwarder inside the namespace exposes it as localhost:port)*;
    - Windows: no supported sandbox; a code source is refused there by name.
  - **Missing sandbox:** a host where the mechanism is not available refuses to start a code source's worker, naming the source and what is missing. It never starts one unsandboxed.

The egress allow-list is the deployment's `udf_egress_allowlist`, the one commands already use (REQ-885). Loopback is not on it for code sources *(proposed: Provisa's own ports are not a code source's to call)*.

## 5. What changes in the Node work already built

All of it is a move, on the unmerged design/node-connector branch:

- `provisa/node/manifest.py` → `provisa/codesource/manifest.py`.
- `bundle.py` → `codesource/bundle.py`, and `uploads.py` → `codesource/uploads.py`. The `org_node_bundles` table becomes `org_code_bundles`, keyed `(org_id, content_hash)`.
- The Git fetch in `install.py` → `codesource/git.py`.
- `runtime_deps/js_runtimes.py` → `runtime_deps/code_runtimes.py`, with Python's pins beside Node's.
- `provisa/node/` keeps the Node-only parts: the npm fetch and install, `reader.mjs`, `reader.py`, `host.mjs`.
- The `BundleRefused` codes `node.*` become `codesource.*`.

The Node note keeps its decisions; it points here for the shared parts.

## 6. Python (REQ-1993)

### 6.1 What the code says

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class RiskRow:
    account_id: str
    score: float
    computed_at: datetime
    reasons: list[str]

def churn_risk(account_id: str, as_of: datetime | None = None) -> list[RiskRow]:
    """Churn risk of one account.

    @table
    """
```

- **Tags:** a line of the docstring that is exactly `@table`, `@command` or `@stream` *(proposed: a tag is its own line, so prose that mentions "@table" is not a tag)*.
- **Description:** the docstring with its tag lines removed.
- **Unknown tags:** a line starting with `@` that is not one of the three is an unknown tag, refused by name *(proposed: Python has no standard docstring tag syntax beginning with `@`, unlike JSDoc)*.
- **Functions:** a module-level function only (REQ-1993); a method or a lambda is ignored.
- **Parameters:** a parameter without a default is required by the source; one with a default is not. `*args` and `**kwargs` are refused by name.
- **Rows:** a `@table` returns a collection: `list[T]`, `Iterable[T]`, `Iterator[T]`, `Generator[T, ...]`, `AsyncIterable[T]`, `AsyncIterator[T]`, `AsyncGenerator[T, ...]`, or an `async def` returning one of those. A `@stream` is a generator or an async generator (REQ-1993).
- **Named types:** a `dataclass`, `TypedDict`, `NamedTuple` or annotated class *(REQ-1993 names dataclass, TypedDict and annotated class; NamedTuple is proposed)*. Fields come from the annotations; `X | None` and `Optional[X]` are nullable; a TypedDict field that is `NotRequired` is optional.
- **Scalars:** `str` → text; `int` → bigint; `float` → double; `bool` → boolean; `Decimal` → numeric; `datetime` → timestamp; `date` → date *(proposed: the IR has date)*; `Literal["a", "b"]` → enum; `enum.Enum` with string values → enum; `dict[str, X]` → json; `Any` → json; `list[X]` → a list.

### 6.2 The reader

Python's annotations are not readable without importing the module: a type hint can name a type from another module or a dependency. So the Python reader imports the code, and **it runs in the same sandbox as the worker** (section 4). Importing the code is running it.

`reader.py` *(proposed)* is shipped with Provisa and runs under the source's pinned Python, with the installed code on its path. It imports the entry module and:
- for each module-level function, reads its docstring with `inspect.getdoc` and its hints with `typing.get_type_hints(include_extras=True)`;
- writes the trees of section 2;
- writes an import error as a diagnostic: the code is refused, with the error.

**Entry module** (decision P1). The organisation's code is never changed for Provisa:
- the entry module is the code's single top-level import: for a wheel, from its `top_level.txt` or `RECORD`; for an upload or a Git subdirectory, its single top-level module or package;
- when there is more than one, the source registration form names the module, a field Provisa keeps with the source;
- when there is more than one and the form names none, the source is refused, naming the candidates.

### 6.3 Fetching the code and installing its dependencies

**The code.** One of three references; each is pinned, and the content hash is taken before any install:
- a PyPI package at an exact version, from the organisation's index for it, else the public PyPI;
- a Git repository at a commit, with a subdirectory: the shared Git fetch;
- an uploaded archive: the shared uploads store.

A package is fetched as its **wheel**, checked against the index's published SHA-256. An sdist is refused *(proposed: building an sdist runs its build backend, the Python counterpart of an install script, which the maintainer ruled out for Node)*.

**The lockfile.**
- A code with dependencies carries `uv.lock`, `pylock.toml` (PEP 751) or a `requirements.txt` with `--hash` on every line;
- one without dependencies needs none.

**The install** *(proposed)*:
- uv, pinned and hashed like a runtime, installs into a virtual environment inside the code's cache directory;
- for `uv.lock`: `uv sync --frozen --no-build --no-install-project`;
- for the other lockfiles: `uv pip install --require-hashes --no-build --only-binary :all:`;
- the index configuration is written into the install's own directory (`uv.toml` with the index URLs, and credentials in environment variables uv reads per index) and removed after it, exactly as Node's `.npmrc`;
- the result is cached by content hash.

**The runtime** *(proposed)*: CPython from astral-sh/python-build-standalone, at a pinned release and Python version, for the three platforms, with each archive's SHA-256 recorded. It is fetched on demand and cached beside the JS runtimes. The release and version are chosen when part P2 is built, from releases at least two weeks old.

### 6.4 Package indexes

REQ-1993 asks for the organisation's package indexes, "like REQ-1984's registries". *(Proposed: the same admin page and table, with a third kind.)*
- **PyPI index:** a URL and a credential, one of which may be the default index every install goes through, like npm's mirror.
- **No scope:** Python packages have none, so the page shows no scope for this kind.
- **Same rules:** every field is kept as entered and resolved at use.
- **The page** becomes "Package registries" with three lists: npm registries, PyPI indexes, Git hosts.

### 6.5 Tables, commands and live tables

Identical to Node's parts 5 to 7:
- the parameters are REQ-1986's, with the shared kind `query_arg`;
- landing per argument set through REQ-1980's branch and converter;
- commands use a new `impl_kind`, `code` *(proposed: one kind for every language, the binding naming the source and the export)*;
- each live-table subscription starts its own generator.

## 7. Sequence

1. **Shared layer** (this note's sections 1 to 5): move the Node parts, generalise the runtime resolver, and write `codesource/worker.py` with Node's `host.mjs`. This is Node part 4, built language-neutral.
2. **The sandbox** (section 4): the proxy, the macOS and Linux mechanisms, and Deno's flags. It is Node part 4b and serves every language.
3. **Python, part P1:** the reader and its mapping into the shared manifest, with `host.py`.
4. **Python, part P2:** runtime and uv pins, the PyPI fetch, the lockfile install, and the PyPI kind of package registries.
5. **Node parts 5 to 7, then Python's:** tables, commands and live tables. They are the same code paths and wait for REQ-1986 and REQ-1980 as before.

## 8. Tests

The same shape as Node's.

**Unit:**
- the reader's trees written by hand for the mapping rules;
- the worker protocol against a stub host written in Python;
- the sandbox profile and arguments as data.

**Integration (CI):**
- the real reader and the real worker under each runtime (Node, Bun, Deno, CPython), against a fixture package that is the same API in both languages, with the same manifest expected from each;
- the sandbox refusing a file read outside the code and a connection to a host off the allow-list, on Linux (CI) and on macOS (where CI has it).

## 9. Decisions (lead, 2026-10-12)

- **P1. Entry module.** The code's single top-level import; with several, the source registration form names it. No key in the organisation's code.
- **P2. sdists.** Wheels only.
- **P3. Python's runtime.** python-build-standalone, pinned and hashed.
- **P4. Python's lockfiles.** `uv.lock`, `pylock.toml`, or a hashed `requirements.txt`.
- **P5. `Decimal`.** Maps to numeric, sent as a string on the wire. Parity is a rule of query surfaces, not of languages: Node simply has no decimal.
- **`int`.** Maps to bigint.
- **S1. The sandbox for Node, Bun and Python.** An OS mechanism (macOS `sandbox-exec`, Linux bubblewrap) with a host-filtering local proxy for the allow-list.
- **S2. Windows.** A code source is refused on Windows, by name.
- **S3. Loopback.** Not reachable from a code source.
