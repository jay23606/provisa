# Replicas

A replica is a copy of a source table that Provisa keeps in the engine's materialization store and reads instead of the source. This page covers what a replica is indexed on, where to keep replicas, and how fresh they are. Whether a table is replicated at all is set by [`replicate`](configuration.md#the-replicate-setting) and by what the engine can reach; see [What an engine changes](engines.md#what-an-engine-changes). (REQ-826)

## Replicas are indexed

Provisa indexes a replica the way the model uses its table. (REQ-2015) [tool-verified: `provisa/federation/replica_indexes.py` `plan`, `join_columns`]

- **The declared primary key**, enforced as a key.
- **The columns declared relationships join on**:
  - the foreign key of each relationship whose source is this table;
  - the target column of each relationship whose target is this table, unless that column is already the key;
  - both foreign keys of a junction table that a relationship traverses.

Take this relationship:

```yaml
relationships:
  - id: orders-to-customers
    source_table_id: orders
    target_table_id: customers
    source_column: customer_id
    target_column: id
    cardinality: many-to-one
```

The replica of `orders` gets its key and an index on `customer_id`. The replica of `customers` gets its key, and when `id` is that key it needs nothing more. A join of the two then reads an index on both sides, in a store that uses indexes for joins (see [What each store builds](#what-each-store-builds)). A relationship on a computed column the replica does not hold gets no index. [tool-verified: `provisa/federation/replica_indexes.py` `plan`]

Declare the key with `is_primary_key: true` on the column. A replica with no declared key gets only its join indexes. [tool-verified: `provisa/federation/replica_builds.py` `plan_indexes`]

### Readable first, indexed after

A landing never waits for indexes. The replica is read from the moment it is swapped in; the replica runner then builds its indexes one at a time, in a separate pass, under a per-replica index lock. [tool-verified: `provisa/federation/replica_runner.py` `_planned`, `_start_index_builds`] Expect the first queries after a landing to run without them.

Each landing records the indexes it asked for, the ones built, and the ones that failed, by name, on the replica's record in the control plane (`replica_state.index_state`). [tool-verified: `provisa/federation/replica_state.py` `record_index_plan`, `settle_index_state`]

- **A failed index never fails the landing.** It is logged with its cause and asked for again by the next landing. The log line reads `replica of <source>.<schema>.<table>: index <name> on (<columns>) failed: <cause>`. [tool-verified: `provisa/federation/replica_indexes.py` `build_due`]
- **Rows that repeat a declared key are their own failure**, code `replica.index_duplicate_key`, naming the key's columns. The source holds duplicates of a column set the model declares unique. A retry does not fix that: correct the data at the source, or correct the declared key. [tool-verified: `provisa/federation/replica_indexes.py` `DuplicateKey`, `DUPLICATE_KEY`]
- **A landing that replaces the table mid-build** leaves the earlier builds behind; they stop and record nothing, and the new table gets its own. On a PostgreSQL store the swap cancels a build still running on the table it replaces. [tool-verified: `provisa/federation/replica_target.py` `_pg_swap`; `provisa/federation/replica_indexes.py` `build_due`]
- **The plan follows the model at each landing.** A relationship added later gets its index at the replica's next landing. [tool-verified: `provisa/federation/replica_builds.py` `plan_indexes`]

The admin UI does not show the index record. Read the server log, or the `index_state` column of the replica's row. [tool-verified: no reader of `index_state` outside `provisa/federation/replica_state.py` and `replica_indexes.py`]

### What each store builds

| Store | What is built | How |
| --- | --- | --- |
| PostgreSQL: the `pg` engine's own database, the PostgreSQL store of Trino or DuckDB, the `sqlalchemy` engine on PostgreSQL | Key and join indexes | `CREATE INDEX CONCURRENTLY` on its own connection, so readers and writers are not blocked. The key is built as a unique index, then made the primary key with `ADD CONSTRAINT ... PRIMARY KEY USING INDEX`. An invalid index a cancelled build left is dropped and built again. |
| Other databases behind a relational engine (`mysql`, `oracle`, `mssql` and the rest) | Key and join indexes | The dialect's own DDL. A database that refuses the DDL records the index as failed. |
| Embedded DuckDB file, MotherDuck | Key and join indexes | Through the store broker: `ALTER TABLE ... ADD PRIMARY KEY`, `CREATE INDEX IF NOT EXISTS`. |
| ClickHouse | The sorting key only | A ClickHouse replica is ordered by its declared key (`ORDER BY`), set when it lands. ClickHouse has no secondary B-tree index to build. |
| Snowflake, BigQuery, Databricks, Fabric, Synapse | Nothing | The warehouse organizes the table itself. |

[tool-verified: `provisa/federation/replica_target.py` `PostgresIndexer`, `SqlAlchemyIndexer`, `DuckDBStoreIndexer`; `provisa/federation/materialize_broker.py` `_SyncedStore.replica_index`; `provisa/federation/clickhouse_store.py` `create_ddl`; `replica_indexer` in `backend.py`, `pg_backend.py`, `duckdb_backend.py`, `sqlalchemy_backend.py`, `clickhouse_backend.py`, `snowflake_backend.py`, `bigquery_backend.py`, `databricks_backend.py`, `mssql_warehouse_backend.py`]

An index only helps a join that runs where the index is. Two engines read their store without using its indexes for joins:

- **DuckDB with its embedded file.** The engine never attaches the file. Each statement reads its own local copy of every store table it names, made again whenever the store has changed. Joins run as hash joins over that copy, so join indexes do not speed them up; the file's indexes enforce the key and serve whatever reads the file in place. [tool-verified: `provisa/federation/duckdb_runtime.py` `_store_is_file`, `_copy_store_table`; `provisa/federation/replica_target.py` `DuckDBStoreIndexer`]
- **DuckDB with a PostgreSQL store.** DuckDB reads the store through its `postgres` extension with filter pushdown switched off (upstream bug duckdb/duckdb-postgres#564), so it scans the replica and filters and joins in DuckDB. The store's indexes are built but these reads do not use them. [tool-verified: `provisa/federation/duckdb_extensions.py` `_EXTENSION_SETTINGS`]

A MotherDuck store is attached and read in place. [tool-verified: `provisa/federation/duckdb_runtime.py` `_store_is_file`]

## Use a relational database as the replica store where the engine runs SQL in it

When the engine runs its joins inside a relational database, keep the replicas there. The joins then read the indexes above. Three setups do that:

- **The `pg` engine.** Replicas land in the engine's own PostgreSQL database and every statement runs there, through their indexes. [tool-verified: `provisa/federation/pg_backend.py` `replica_target`, `replica_indexer`]
- **A relational engine** (`mysql`, `oracle`, `mssql`, the `sqlalchemy` catch-all and the rest). Every source lands into that database and is queried there. [tool-verified: `provisa/federation/sqlalchemy_backend.py` `replica_indexer`; [Engine reference](configuration.md#engine-reference)]
- **Trino with its PostgreSQL store.** PostgreSQL is the only store Trino supports; Trino reads replicas through its PostgreSQL connector. [tool-verified: `provisa/federation/engine.py` `build_trino_engine` `supported_materialize_stores`; `provisa/federation/backend.py` `TrinoBackend.materialize_store_target`] A filter or join Trino pushes down to PostgreSQL uses the indexes; work Trino does itself does not. [inferred]

Point an engine at a store with `PROVISA_MATERIALIZE_URL` or `materialize_store_url`; an org's own registered store takes precedence over both. [tool-verified: `provisa/federation/engine.py` `materialize_store`, `configured_materialize_url`]

```bash
PROVISA_MATERIALIZE_URL="postgresql://provisa:secret@replicas.internal:5432/replicas"
```

This is a general recommendation, not a rule. Whether it pays depends on the engine, the sources, the store and the table sizes. Weigh these:

- **Per-query reach.** A store the engine reaches over the network adds a round trip and a transfer to every read. The embedded DuckDB file is local and columnar, and scans fast. [inferred]
- **Landing cost.** Writing a replica into a relational database, then building its indexes, costs more than writing a local file. [inferred]
- **The database's own load.** Replica reads, landings and index builds all run on that database. Size it for them. [inferred]
- **Large scans.** An index does nothing for a query that reads most of a large table. A columnar store scans it faster than a row store. [inferred]

## Choosing where replicas live

The store is one lever among several, and they overlap. Settle the others first; the store decides only what they leave.

| Lever | What it does | Where it helps |
| --- | --- | --- |
| Hot tables | A small lookup table is held in Redis and put into each query that reads it as an inline `VALUES` CTE (common table expression). [tool-verified: `provisa/compiler/sql_gen.py`, `provisa/cache/hot_tables.py`] | Joins to small lookups, on any store: the rows travel inside the query. The target of a many-to-one relationship, or a table at or under `hot_tables.auto_threshold` rows (1,000 by default), is made hot when first read. `hot: true` forces a table in and `hot: false` keeps it out. [tool-verified: `provisa/cache/hot_tables.py` `promote_on_read` and the loader that registers candidates; `provisa/core/models.py` `HotTablesConfig`, `Table.hot`] |
| Materialized views you define | A view with `materialize: true` is stored and refreshed. A query that reads the view is answered from the stored rows when it is fresh and the reader sees it whole: no input carries a row rule narrower than everything. [tool-verified: `provisa/mv/view_read.py` module docstring] | Aggregates over large tables. You decide which ones exist; none is created for you. See [Views](configuration.md#views-governed-computed-datasets). |
| Relationship `materialize: true` | A cross-source relationship gets a stored, pre-joined parent-child view. A request whose join matches the pattern, fully or in part, is rewritten to read it, whether it arrives as SQL or as a query the compiler builds. [tool-verified: `provisa/api/app_loaders.py` `_load_mv_and_views_config`; `provisa/mv/view_reinject.py` `reinject`; `provisa/pgwire/_pipeline.py` `_view_answering`] | Joins on a store that builds no join indexes. See [Auto-Materialization](configuration.md#auto-materialization). |
| Placement | Sources the engine can read live are read live; the rest are replicated. What ends up in the store follows from the engine you pick. [tool-verified: `provisa/federation/replica_routing.py`] | Choosing the engine decides most of what the store has to hold. |

Relationship materialization and indexed joins answer the same need in two ways. On a columnar or warehouse store (the DuckDB file, ClickHouse, Snowflake, BigQuery, Databricks, Fabric, Synapse) no join index is built, so a pre-joined view is how a frequent join gets cheap. On a relational store the join columns are indexed already, and the same joins can run fast without materializing them. [inferred]

What still depends on the store: ad-hoc scans and joins over large tables that no materialized view covers and no hot table serves. Those run on the store's indexes in a relational database, or on its scan speed in a columnar one.

Results vary by workload. Measure before and after a change with the [sizing tool](sizing.md); its [live-or-replica runs](sizing.md#live-or-replica-reads-and-the-ttl) give a replica read's cost against a live read's on your deployment.

## Freshness

Make freshness part of the decision, next to speed. How old an answer may be, and what keeping it current costs the source, decide whether a table is read live or from a replica, and so what the store has to hold.

Enterprise sources rarely support real time. Data arrives by batch load or nightly ETL, change feeds lag, and many systems cannot take live reads at query volume. Start from the freshness each table needs, then pick the cheapest strategy that meets it. The operator-side rules are in [Freshness and load: who decides](configuration.md#freshness-and-load-who-decides).

| Strategy | Set with | What it guarantees | What it costs the source |
| --- | --- | --- | --- |
| Live read | `replicate: -1` | Current as of the query | Every query reads the source |
| TTL | `change_signal: ttl`, `cache_ttl` | A replica no older than `cache_ttl` | One rebuild per `cache_ttl`; with a `watermark_column`, only rows past the watermark |
| Change probe | `change_signal: probe` or `ttl_probe`, `cache_ttl` | Rebuilt only after the probe reports a change; the probe runs every `cache_ttl` | One probe per interval, and a rebuild only on change |
| Push change feed | A Kafka or WebSocket source; `change_signal: debezium` on a source with a `cdc` block; `change_signal: native` on PostgreSQL, MongoDB or Cosmos DB | Current to within the feed's lag and the debounce | Kafka, WebSocket and Debezium: none after the first build, the feed carries the rows. PostgreSQL, MongoDB and Cosmos DB: a rebuild per burst of changes |
| External signal | `change_signal: signal` | Rebuilt each time `POST /data/sources/{source_id}/signal` says the source changed; never on a clock | One rebuild per signal |
| Per-role TTL | `role_ttl` on a table | A listed role accepts a replica up to its own TTL; the table's `cache_ttl` stays the floor | Fewer rebuilds: a tolerant role's read never asks for one |
| Load protection | `load_protected: true`, with `cache_ttl`, a probe or an `off_peak_window` | Queries never read the source; the runner alone refreshes the replica, and with an off-peak window only while it is open | Only the scheduled refreshes |
| Freshness gate | `freshness_gate: true` on a source | Each read is checked against the source's `change_signal` and `cache_ttl` first; a stale verdict refreshes before the read | A refresh in the read path when stale |

[tool-verified: `provisa/core/replicate.py`; `provisa/federation/replica_builds.py` `_next_refresh_at`, `_probe_decides`; `provisa/federation/query_residency.py` `freshness_verdict`, `is_stale_of`; `provisa/federation/role_ttl.py` `effective_ttl`; `provisa/freshness/source_gate.py` `gate_source`; `provisa/events/push_wiring.py` `wire_push_listeners`, `_run_change_stream`]

A probe that has nothing to compare (no watermark, sentinel or probe query) degrades to the TTL. [tool-verified: `provisa/federation/replica_builds.py` `_probe_decides`]

### Near real time from a change feed

Where a source cannot take live query load but already publishes its changes, a change feed gives near-real-time data without touching the source at query time. Queries read the local replica, which is fast and puts no load on the source, while the event loop applies changes as they arrive. The data lags only by the feed, typically seconds. [inferred: the lag figure]

The feed being there is not enough. Provisa follows it only for a table that is wired to it:

- **A Kafka source.** The table names its topic, and each change is applied to the replica by primary key, deletes included. [tool-verified: `provisa/events/push_wiring.py` `_build_provider`, `_run_listener`; `provisa/subscriptions/cdc_landing.py`]

  ```yaml
  live:
    strategy: kafka
    kafka:
      topic: orders.cdc
  push_debounce_quiet: 0      # seconds of quiet before a batch lands; 0 lands each message
  push_debounce_max_delay: 5  # a batch never waits longer than this
  ```

- **A WebSocket source.** Its stream is applied the same way. [tool-verified: `provisa/events/push_wiring.py` `_build_provider`]
- **A table with `change_signal: debezium`** (on the table or its source) on a source whose `cdc` block names the Kafka transport and the connector's topic prefix. The first read builds the replica; after that, each change event on the topic `{topic_prefix}.{schema}.{table}` is applied by primary key, deletes included, and the offset is committed only once the change has landed. [tool-verified: `provisa/events/push_wiring.py` `_captured_by_cdc`, `_cdc_provider`; `provisa/subscriptions/debezium_provider.py` `ack`]
- **A table of such a source with `change_signal: kafka`**. Its changes are read from the delta topic its `live.kafka.topic` names, on the same transport, and applied the same way; a table on this signal that names no topic is refused by name when it or its source is saved and when the config loads. [tool-verified: `provisa/events/push_wiring.py` `_cdc_provider`; `provisa/core/change_signal.py` `kafka_topic_refusal`]
- **A MongoDB or Cosmos DB table with `change_signal: native`** (on the table or its source). Each burst of changes on the change stream asks for a rebuild of the replica. [tool-verified: `provisa/events/push_wiring.py` `_change_feed_opted_in`, `_run_change_stream`]
- **A PostgreSQL table with `change_signal: native`** (on the table or its source). Provisa reads the database's logical replication from a slot of its own, `provisa_<source id>`, over a publication of the same name that lists the source's native tables. No Kafka is involved. Each burst of changes to a table asks for a rebuild of its replica. The database needs what Debezium needs: `wal_level` set to `logical`, a role with the replication right that may create the publication, and a primary rather than a read replica; a source that lacks one is refused by name when it is saved and when the config loads. The slot and the publication are made when the first table follows them and dropped when the last one stops or the source is deleted. When a server starts, it checks every registered PostgreSQL source and drops a Provisa slot that no native table follows, so a slot left by a configuration changed while no server ran does not keep holding the source's WAL. [tool-verified: `provisa/subscriptions/pg_logical.py`; `provisa/events/push_wiring.py` `_run_logical_stream`, `_drop_unfollowed_slots`]

A pushed table needs a declared primary key; one without is skipped and logged. [tool-verified: `provisa/events/push_wiring.py` `wire_push_listeners`]

A table with a push change signal counts as fresh on the read path, because its feed is its freshness check. [tool-verified: `provisa/federation/query_residency.py` `freshness_verdict`] So a push signal nothing would receive is refused: `change_signal: native` on any type other than Kafka, WebSocket, ingest, PostgreSQL, MongoDB or Cosmos DB is refused when the source or table is saved and when the config loads, and so is `debezium` on a source with no `cdc` block. [tool-verified: `provisa/core/change_signal.py` `native_signal_refusal`; `provisa/core/config_loader.py` `_validate_change_signal`; `provisa/api/admin/_change_feed.py` `table_change_feed_refusal`]
