# CLI Reference

The `provisa` command is the single entry point for the pip-installed embedded tier (REQ-1128).
It starts the runtime, manages licenses, triggers metadata publishing, deploys models, and
controls the maintenance banner — without Docker, Node, or any external services.

Install it with the `embedded` extra, which also pulls in the offline DuckDB extensions
and the embedded PostgreSQL control plane:

```bash
pip install 'provisa[embedded]'
```

**Platform requirements.** `provisa run` requires Python 3.12 and a platform with a pgserver
wheel: linux x86_64, macOS, or Windows x86_64. Linux aarch64 has no pgserver wheel and no source
distribution, so the embedded tier does not run there. Use the container tier on aarch64.
[tool-verified: `_require_supported_interpreter()` at cli.py:513-546]

---

## Shared options

Several subcommands call the Provisa HTTP API. They share three flags and two environment
variables. [tool-verified: `_api_call()` at cli.py:345-376; each subcommand's argparse block
at cli.py:653-773]

| Flag | Default | Env var fallback |
| --- | --- | --- |
| `--api <url>` | `http://127.0.0.1:8000` | `PROVISA_API_URL` |
| `--token <token>` | _(none)_ | `PROVISA_API_TOKEN` |
| `--timeout <seconds>` | 300 (30 for `maintenance`) | _(none)_ |

`--api` is the base URL of a running Provisa instance. Under multitenancy the host names the
organization — `https://acme.provisa.org` routes to acme's tenant. `--token` is a Bearer token;
when it is empty no `Authorization` header is sent, which is correct for unauthenticated
deployments. [tool-verified: cli.py:314-316, 357-365]

Set both variables in your CI environment to avoid repeating them on every call:

```bash
export PROVISA_API_URL=https://acme.provisa.org
export PROVISA_API_TOKEN=<token>
```

Subcommands that accept these flags: `metadata export`, every `env` subcommand (`list`, `show`,
`create`, `delete`, `diff`, `merge`, `deploy`, `revert`, `redo`, `fetch`, `push`, `pull`),
`maintenance on`, `maintenance off`, `maintenance status`.

---

## provisa run

Start the embedded Provisa system — API server and UI static/proxy server — in a single process.
No Docker, no Node, no external services. [tool-verified: cli.py module docstring lines 11-23;
`_cmd_run()` at cli.py:549-602]

```
provisa run [--demo] [--host HOST] [--api-port PORT] [--ui-port PORT]
            [--no-browser] [--reset] [--data-dir DIR]
```

### Flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--demo` | off | Load the bundled demo — pet-store and shelter sample domains over embedded SQLite (REQ-414) |
| `--host` | `127.0.0.1` | Bind address for both servers |
| `--api-port` | `8000` | API server port |
| `--ui-port` | `3000` | UI static/proxy server port |
| `--no-browser` | off | Skip opening a browser when the UI is ready; still prints the URL |
| `--reset` | off | Drop and rebuild the embedded control-plane store before starting; use after a Provisa upgrade if startup reports a schema mismatch |
| `--data-dir` | `~/.provisa/native` | Directory that holds the embedded PostgreSQL cluster and DuckDB extension cache |

[tool-verified: run subparser at cli.py:609-634]

### Environment variables

`provisa run` reads several additional variables before the HTTP servers start.
Set them to override the defaults that `load_profile("native", ...)` would otherwise apply.
[tool-verified: `_apply_embedded_env()` at cli.py:83-116]

| Variable | Effect |
| --- | --- |
| `TRINO_HOST` / `TRINO_PORT` | Replace the embedded DuckDB engine with a customer-supplied Trino coordinator (REQ-1129) |
| `PROVISA_ENGINE_URL` | Alternative way to point at an external federation engine |
| `PROVISA_CONFIG` | Config file to load; `--demo` sets this to the bundled demo config (REQ-1127) |
| `PROVISA_DEMO` | Set to `1` by `--demo`; marks the session as a demo run |
| `PROVISA_DEMO_DIR` | Path to the demo's sample-data directory; set by `--demo` |
| `PROVISA_DUCKDB_EXT_DIR` | Pre-staged DuckDB extension directory; set automatically from the `provisa-duckdb-ext` package if present; absent means DuckDB downloads from the network on first use |

[tool-verified: `_apply_demo_config()` at cli.py:67-80; `_apply_embedded_env()` at cli.py:83-116]

### Startup sequence

1. Platform check — aborts with a clear message on unsupported Python or missing pgserver.
2. `--reset` (if requested) — drops the embedded PostgreSQL cluster; it rebuilds on the next step.
3. Demo config (if `--demo`) — sets `PROVISA_CONFIG` and `PROVISA_DEMO_DIR`.
4. Embedded environment — starts the PostgreSQL control plane, resolves its socket URL, and
   stages offline DuckDB extensions if `provisa-duckdb-ext` is installed.
5. Schema drift check — scans the live control plane for missing columns. If any are found,
   prints a `--reset` hint and exits with code 1. V1 has no migrations; a column added in a
   newer release requires a reset. [tool-verified: `_control_plane_drift()` at cli.py:119-162]
6. Both servers start concurrently. The ready announcer polls `GET /ready` (not `/health` — the
   `/ready` endpoint confirms the store is attached and the engine is warm) and opens the browser
   when it returns 200. [tool-verified: `_announce_ready()` at cli.py:182-224]

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Clean shutdown (Ctrl-C) |
| 1 | Startup error (platform check failed, demo config missing, schema drift detected) |

### Example

```bash
# Start with the demo data
provisa run --demo

# Start on non-default ports, no browser
provisa run --api-port 8080 --ui-port 4000 --no-browser

# Upgrade: reset the control plane first, then start
provisa run --reset

# Point at an external Trino cluster instead of the embedded DuckDB engine
TRINO_HOST=trino.internal TRINO_PORT=8080 provisa run
```

---

## provisa license apply

Verify and install a license file offline (REQ-1139). The file is the `license.json` issued by
provisa.dev. [tool-verified: `_cmd_license_apply()` at cli.py:271-280]

```
provisa license apply <file>
```

| Argument | Notes |
| --- | --- |
| `file` | Path to the license file; `~` expansion is applied |

Exit code 0 means the license is valid and installed. Exit code 1 means it was rejected; the
reason prints to stderr. [tool-verified: cli.py:276-280]

```bash
provisa license apply ~/Downloads/license.json
```

---

## provisa license status

Show the machine ID, trial state, elapsed days, and license validity (REQ-1139).
[tool-verified: `_cmd_license_status()` at cli.py:283-299]

```
provisa license status
```

No flags. Prints four lines — machine ID, first-seen date, elapsed days, trial state, and
license state — and exits 0. [tool-verified: cli.py:293-299]

```
Machine ID:   a1b2c3d4e5f6...
First seen:   2026-07-01
Elapsed:      83.0 days
Trial:        active
Licensed:     no (no license installed)
```

---

## provisa metadata export

Trigger the running server's on-demand metadata publish (REQ-1072/REQ-1074). Posts to
`POST /admin/metadata-export/publish` — the same endpoint the Admin tab's **Publish now**
button calls, so both paths send the same full snapshot. [tool-verified: `_cmd_metadata_export()`
at cli.py:302-342]

```
provisa metadata export [--api URL] [--token TOKEN] [--timeout SECONDS]
```

| Flag | Default | Notes |
| --- | --- | --- |
| `--api` | `$PROVISA_API_URL`, then `http://127.0.0.1:8000` | Under multitenancy the host names the org |
| `--token` | `$PROVISA_API_TOKEN` | Bearer token for an identity holding `org_settings`; omit on unauthenticated deployments |
| `--timeout` | `300` | Seconds before the HTTP call is abandoned |

[tool-verified: cli.py:654-669]

| Exit code | Meaning |
| --- | --- |
| 0 | Every asset published |
| 1 | Partial publish or connection failure; per-asset errors print to stderr |

[tool-verified: cli.py:335-342]

```bash
provisa metadata export \
  --api  https://acme.provisa.org \
  --token "$PROVISA_API_TOKEN"

# Cron example — daily at 06:00
# 0 6 * * *  provisa metadata export --api https://acme.provisa.org >> /var/log/provisa-export.log 2>&1
```

The full configuration reference — providers, credentials, `reconcile_cron`, and what the
snapshot contains — is in [Metadata Export](metadata-export.md#from-the-command-line).

---

## provisa env

Run the environment lifecycle against a running Provisa (REQ-1498). Every subcommand is a call to
the admin API the UI calls; the CLI decides nothing. The allow-list of what a copy carries, the
merge and removal rules, binding, protection and the caller's rights are the server's, so they
hold however the operation is invoked. [tool-verified: cli_envs.py:11-28]

```
provisa env {list,show,create,delete,diff,merge,deploy,revert,redo,fetch,push,pull} --org ORG ...
```

### Flags every subcommand takes

| Flag | Required | Notes |
| --- | --- | --- |
| `--org` | yes | Organization holding the environment |
| `--json` | no | Print the API's answer as JSON, for a script |
| `--api` | no | See [Shared options](#shared-options) |
| `--token` | no | Bearer token for an identity that may perform the operation |
| `--timeout` | no | Seconds; default 300 |

Subcommands that act on one environment also take `--env ENV` (required). `list`, `diff`,
`merge` and `fetch` do not; `diff` and `merge` name their environments with `--from` and `--into`.
[tool-verified: cli_envs.py:349-374, `_command()`]

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Done, or a dry run that applied nothing |
| 1 | Refused. The refusing rule's code prints on stderr as `refused (<code>): <detail>`; under `--json` it is `{"refused": {...}}` on stdout |
| 2 | Proposed, not applied: the target environment is protected and the change waits for an approval |

Exit code 2 is intentional. A pipeline that treated a pending approval as a released deploy would
be wrong. [tool-verified: cli_envs.py:21-28, 40-41, 64-78, 120-135]

### provisa env list

List the org's environments and the build each is at. No flags beyond the shared ones.
[tool-verified: cli_envs.py:141-149]

```
provisa env list --org ORG [--json]
```

### provisa env show

Show one environment and its current build. Exits 1 with `environments.unknown` when the
environment does not exist. [tool-verified: cli_envs.py:163-183]

```
provisa env show --org ORG --env ENV [--json]
```

### provisa env create

Create an environment holding another's model, with its data chosen at creation (REQ-1942). The API
decides which choices the caller may make. [tool-verified: cli_envs.py:197-216]

```
provisa env create --org ORG --env NAME --data-mode MODE
                   [--from SOURCE] [--mutation-handling HANDLING] [--expires-at ISO8601]
```

| Flag | Required | Notes |
| --- | --- | --- |
| `--env` | yes | Name of the new environment |
| `--from` | no | Environment to start from; default `prod` |
| `--data-mode` | yes | `inherit`, `unbound`, `test_fake` or `test_synthetic`: the source's connections by reference, none until it binds its own, or test data |
| `--mutation-handling` | no | `refused`, `reversible` or `direct`; default `refused` |
| `--expires-at` | no | ISO-8601 instant after which the environment is deleted |

[tool-verified: cli_envs.py:391-416]

```bash
provisa env create --org acme --env feature-x --from prod --data-mode test_fake
```

### provisa env delete

Retire an environment. Its branches go only when named. [tool-verified: cli_envs.py:219-232]

```
provisa env delete --org ORG --env ENV [--delete-branch] [--delete-remote-branch]
```

| Flag | Notes |
| --- | --- |
| `--delete-branch` | Also delete its branch |
| `--delete-remote-branch` | Also delete its branch on the remote |

[tool-verified: cli_envs.py:418-424]

### provisa env diff

Report what merging one environment into another would do. It is a GET of `merge-preview`, so it
cannot write; hand it to a runner that must not change anything. [tool-verified:
cli_envs.py:186-191]

```
provisa env diff --org ORG --from SOURCE --into TARGET [--removals]
```

| Flag | Required | Notes |
| --- | --- | --- |
| `--from` | yes | Environment merged from |
| `--into` | yes | Environment merged into |
| `--removals` | no | Also remove from the target what the source no longer has |

[tool-verified: cli_envs.py:426-439]

### provisa env merge

Merge one environment into another, by identity (REQ-1490). [tool-verified: cli_envs.py:235-250]

```
provisa env merge --org ORG --from SOURCE --into TARGET
                  [--removals] [--dry-run] [--message MSG]
                  [--retire-source] [--retire-remote]
```

| Flag | Required | Notes |
| --- | --- | --- |
| `--from` | yes | Environment merged from |
| `--into` | yes | Environment merged into |
| `--removals` | no | Also remove from the target what the source no longer has |
| `--dry-run` | no | Print the merge report and apply none of it |
| `--message` | no | What the merge does; required to apply |
| `--retire-source` | no | Delete the source once its work has landed |
| `--retire-remote` | no | With `--retire-source`, also delete the source's branch on the remote |

[tool-verified: cli_envs.py:429-451]

### provisa env deploy

Deploy the model at a git ref into an environment, making that tree the environment's current
model (REQ-1496). This is the command a deployment pipeline runs; a deploy is always an
invocation carrying an identity against a named control plane. [tool-verified:
cli_envs.py:253-267]

```
provisa env deploy --org ORG --env ENV --ref REF [--dry-run] [--message MSG]
```

| Flag | Required | Notes |
| --- | --- | --- |
| `--env` | yes | Environment that will hold the deployed model |
| `--ref` | yes | Branch or commit in the org's repository |
| `--dry-run` | no | Report what the deploy would do; apply nothing |
| `--message` | no | Note carried onto an approval request when the target is protected |

[tool-verified: cli_envs.py:453-468]

A load into an existing environment never applies roles. `--seed` is gone: the API refuses a seed
with `environments.seed_only_at_creation`.

```bash
# Fetch remote branches, then deploy
provisa env fetch --org acme --api "$PROVISA_API_URL" --token "$PROVISA_API_TOKEN"

provisa env deploy \
  --org acme --env prod --ref "origin/main" \
  --message "release: $GIT_COMMIT_MSG" \
  --api "$PROVISA_API_URL" --token "$PROVISA_API_TOKEN"
```

### provisa env revert

Put an environment back to a previous build (REQ-1543). With no `--to` it steps back one commit
along the environment's own history. With `--to` it is the ordinary deploy of that build.
[tool-verified: cli_envs.py:270-284]

```
provisa env revert --org ORG --env ENV [--to BUILD] [--message MSG]
```

| Flag | Required | Notes |
| --- | --- | --- |
| `--env` | yes | Environment to revert |
| `--to` | no | Build to deploy; default is the one before the current build |
| `--message` | no | Note carried onto an approval request |

[tool-verified: cli_envs.py:470-480]

### provisa env redo

Step forward again toward the build a revert departed from. [tool-verified:
cli_envs.py:287-301]

```
provisa env redo --org ORG --env ENV
```

### provisa env fetch

Fetch the org's remote branches into its Provisa repository (REQ-1541). Run this before a deploy
when you want to name `origin/<branch>`. Provisa never runs it on a timer. [tool-verified:
cli_envs.py:307-320]

```
provisa env fetch --org ORG
```

Prints one line per fetched branch, `origin/<name>  <sha12>`.

```bash
provisa env fetch --org acme --api "$PROVISA_API_URL" --token "$PROVISA_API_TOKEN"
# origin/main  a1b2c3d4e5f6
# origin/dev   9f8e7d6c5b4a
```

### provisa env push

Send an environment's branch to the org's remote (REQ-1546). Prints `nothing to send` when there
is nothing to push. [tool-verified: cli_envs.py:323-331]

```
provisa env push --org ORG --env ENV
```

### provisa env pull

Apply what the remote holds for an environment (REQ-1547). Prints
`<env> already holds what the remote does` when there is nothing to apply. Exit code 2 applies as
for deploy. [tool-verified: cli_envs.py:334-343]

```
provisa env pull --org ORG --env ENV
```

For the full explanation of environment classes, protection rules, merge reports, and the
approval lifecycle, see [Environments](environments.md#the-env-cli-commands).

---

## provisa maintenance on

Raise the scheduled-maintenance banner on the deployment (REQ-1466). Run this before planned
work that takes the data plane down — for example, before switching
`var.engine_cluster_mode`, which replaces the engine cluster and every shard on it (REQ-1465).
[tool-verified: `_cmd_maintenance_on()` at cli.py:483-495]

```
provisa maintenance on [--message MSG] [--ends-at ISO8601]
                       [--api URL] [--token TOKEN] [--timeout SECONDS]
```

| Flag | Notes |
| --- | --- |
| `--message` | Override the deployment's standard wording; default is the server's standard message |
| `--ends-at` | ISO-8601 instant the work is expected to end, e.g. `2026-08-14T22:30:00Z`; default is no estimate |
| `--api` | See [Shared options](#shared-options) |
| `--token` | Bearer token for an identity holding `platform_settings` |
| `--timeout` | Default 30 s |

[tool-verified: cli.py:743-773]

Prints the resulting banner state and exits 0. Raises `SystemExit` on HTTP or connection failure.

```bash
provisa maintenance on \
  --message "Engine cluster rolling upgrade" \
  --ends-at "2026-09-22T03:00:00Z" \
  --api "$PROVISA_API_URL" --token "$PROVISA_API_TOKEN"
```

---

## provisa maintenance off

Clear the maintenance banner once the work is done (REQ-1466).
[tool-verified: `_cmd_maintenance_off()` at cli.py:498-501]

```
provisa maintenance off [--api URL] [--token TOKEN] [--timeout SECONDS]
```

Prints the resulting banner state (active: false) and exits 0.

```bash
provisa maintenance off --api "$PROVISA_API_URL" --token "$PROVISA_API_TOKEN"
# Maintenance notice: OFF
```

---

## provisa maintenance status

Show the current maintenance banner state without changing it (REQ-1466).
[tool-verified: `_cmd_maintenance_status()` at cli.py:504-507]

```
provisa maintenance status [--api URL] [--token TOKEN] [--timeout SECONDS]
```

Prints the banner state and exits 0.

```
Maintenance notice: ON
  Message:  Engine cluster rolling upgrade
  Since:    2026-09-22T01:15:00Z
  Ends at:  2026-09-22T03:00:00Z
```

---

## Quick reference

| Command | REQ | What it does |
| --- | --- | --- |
| `provisa run` | REQ-1128 | Start the embedded API + UI |
| `provisa run --demo` | REQ-414 | Start with pet-store / shelter sample data |
| `provisa run --reset` | REQ-1535 | Rebuild the control plane before starting |
| `provisa license apply <file>` | REQ-1139 | Install a license file offline |
| `provisa license status` | REQ-1139 | Show machine ID and trial / license state |
| `provisa metadata export` | REQ-1072 | Publish the metadata snapshot on demand |
| `provisa env list --org ORG` | REQ-1498 | List the org's environments and their builds |
| `provisa env show --org ORG --env ENV` | REQ-1498 | Show one environment |
| `provisa env create --org ORG --env ENV --data-mode MODE` | REQ-1942 | Create an environment from another |
| `provisa env delete --org ORG --env ENV` | REQ-1498 | Retire an environment |
| `provisa env diff --org ORG --from A --into B` | REQ-1490 | Preview a merge (read-only) |
| `provisa env merge --org ORG --from A --into B` | REQ-1490 | Merge one environment into another |
| `provisa env deploy --org ORG --env ENV --ref REF` | REQ-1496 | Deploy a ref into an environment |
| `provisa env revert --org ORG --env ENV [--to BUILD]` | REQ-1543 | Step back one commit, or deploy a build |
| `provisa env redo --org ORG --env ENV` | REQ-1543 | Step forward again |
| `provisa env fetch --org ORG` | REQ-1541 | Fetch remote branches into the Provisa repo |
| `provisa env push --org ORG --env ENV` | REQ-1546 | Send an environment's branch to the remote |
| `provisa env pull --org ORG --env ENV` | REQ-1547 | Apply what the remote holds |
| `provisa maintenance on` | REQ-1466 | Raise the maintenance banner |
| `provisa maintenance off` | REQ-1466 | Clear the maintenance banner |
| `provisa maintenance status` | REQ-1466 | Show the current banner state |

## See also

- [Environments](environments.md) — environment model, protected environments, deploy approval lifecycle
- [Metadata Export](metadata-export.md) — catalog providers, configuration, and what the snapshot contains
- [Deployment](deployment.md) — container tier and cloud deployment
