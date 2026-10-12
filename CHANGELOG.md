# Changelog

All notable changes to Provisa are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## v0.1.0-alpha.479

Released 2026-10-09.

### Features

#### Read Refusals

- A read that needs a table whose replica could not be built is refused, naming the table and the error the build recorded: HTTP 503 with code query.replica_build_failed and the table and reason as parameters, gRPC UNAVAILABLE, and the same message on the transports that carry only a message.

#### Role Assignments

- A multi-tenant deployment reads role assignments from Provisa, never from sign-in claims: a configuration that sets multitenancy with auth.assignments_source claims, stated or by default, does not load, the deployment does not start on it, and a settings change that would produce it is refused, each naming both settings and the value to use.

### Changes

#### api

- A float subclass in a response body is encoded as its number

#### api-source

- A throttled call waits as long as the remote asks
- An API source may sign in with a refresh token or as a Google service account
- A refresh-token exchange returns the issuer's replacement, and a client may state no secret
- An access token for a source whose refresh token the issuer replaces on use
- A sign-in on a deployment without identities stores its token with no actor

#### auth

- A multi-tenant deployment that reads assignments from sign-in claims does not start

#### catalog

- The catalog types a column by the product's own vocabulary; a nested column is JSON
- The role's catalog is served over HTTP, and the JDBC driver reads it there

#### catalog-cache

- One rule for every source kind -- column names are loaded lazily
- A source registered from a specification is indexed with its fields

#### config

- The default public address is where a local install's UI is served
- An empty public address is not stated, and the shipped configs default to the served one

#### demo

- The demo model lets the org's admin write a prospective adopter

#### deps

- strawberry-graphql 0.327.2 clears CVE-2026-107727 and CVE-2026-107728; feature file regenerated

#### google-workspace

- The settings a Google Workspace source is set up with
- Reading a mailbox through the Gmail API, and a message into the canonical facts
- A Google Workspace source is added from the picker and its mail tables registered
- A source is connected with the organisation's Google client, and its form asks nothing about sign-in

#### governance

- A column's scope is changed only with the right to change who is served it (#194)
- Only widening a column's scope needs the right to grant it (#194)
- A source kind declares columns sensitive, and registering its table hides and tags them

#### mail-platforms

- An organisation enters a mail platform's client once
- The vault keeps a client secret its platform entry names

#### microsoft-365

- A mailbox read through Microsoft Graph as the six canonical mail tables
- A message whose HTML body Graph will not give keeps its row
- Microsoft 365 is a source type with its six mail tables and its loader
- A Microsoft 365 source is connected with the organisation's client and read

#### openapi

- A success answer declared as 2XX gives the table its columns

#### reads

- A table whose replica cannot be built refuses the read by name, not as a server fault
- The Neo4j endpoint and the table profile answer a refused read as the other surfaces do

#### replication

- A failed replica build is retried with a growing wait, and never given up
- A build carries what its source says of the rows it read
- A completed build's note is recorded on the replica and shown beside its state

#### secrets

- Personal secrets are addressed only within an organisation the caller belongs to
- A central secrets service is read inside the organisation's own prefix
- A refused secret name is answered 400 with its code; the API source auth writer checks it

#### settings

- A retry ceiling below the interval is refused where settings are loaded too

#### source-sign-in

- A source is signed in to its issuer by a person's approval
- An issuer's addresses may depend on the source, and the refresh token is written under the refresh lock

#### sources

- The canonical mail, calendar and task tables as one module with its enum translator

#### sql

- /data/sql takes a statement's values apart from its text, and binds them
- A statement sent without values is governed by the call it always was

#### sql-explorer

- A column of a result that reports no types is typed from its values
- "filters apply to the rows loaded" follows what the server said, not the editor's text
- A value checklist over part of a result says so and takes a value typed by hand

#### ui

- The table editor opens for a registrar who is not shown governance
- The Google Workspace setup, and the page a source sign-in returns to
- The table viewer binds every value and quotes every identifier through one function (#198)
- The source picker finds Google Workspace by gmail, mail and email, and its tile names Gmail
- The Google Workspace setup shows only what it reads
- Admin › Email holds the organisation's mail platforms beside the mail Provisa sends
- Admin › Email names Microsoft 365 and labels its tenant setting

## History

### Phase A: Infrastructure
- Docker Compose setup (PostgreSQL + Trino), dev and prod overlay
- Test infrastructure: conftest.py, fixture factories, sample config
- Dockerfile for stateless Provisa container
- Trino coordinator config, PG connector, demo seed data

### Phase B: Config & Auto-Catalog
- YAML config loader with idempotent PG upsert
- Trino dynamic catalog API (auto-create/delete catalogs on source add/remove)
- Pluggable secrets provider (`${env:VAR}` syntax, extensible to Vault/K8s)
- Pydantic models: Source, Domain, Table, Column, Relationship, Role, RLSRule
- CRUD repositories for all config entities

### Phase C: Schema Generation
- GraphQL SDL generation from registration model + Trino INFORMATION_SCHEMA
- Per-role schema: domain-scoped visibility, column filtering
- Relationship fields (many-to-one as object, one-to-many as list)
- Root query fields with `where`, `order_by`, `limit`, `offset` arguments
- Trino type to GraphQL scalar mapping
- Auto-generated shortest unique names, regex rules, alias override

### Phase D: Query Compilation & Trino Execution
- GraphQL to PG-style SQL compiler (single SQL statement, no N+1)
- SQLGlot transpilation (PG SQL to Trino SQL)
- Nested relationship compilation via LEFT JOIN / subquery
- Parameterized queries (never interpolates values)
- JSON serializer: reconstruct nested GraphQL response from JOIN rows
- FastAPI app factory, `/data/graphql` and `/health` endpoints

### Phase E: Routing & Direct Execution
- Smart routing: single RDBMS source direct, multi-source via Trino
- SQLGlot transpilation to target dialects (PostgreSQL, MySQL, SQL Server, DuckDB, Snowflake, BigQuery)
- Connection pool per registered RDBMS source (configurable min/max)
- Steward route override hint

### Phase F: Security Layers
- RLS WHERE clause injection per role per table
- Schema visibility enforcement (unauthorized tables/columns excluded from SDL)
- Rights model with 8 independent capabilities
- Column stripping for unauthorized columns

### Phase G: Mutations
- INSERT/UPDATE/DELETE via GraphQL (`insert_<table>`, `update_<table>`, `delete_<table>`)
- Mutations always route direct to RDBMS (never Trino)
- RLS injected into UPDATE/DELETE WHERE clauses
- Write permission enforcement per column per role
- NoSQL and cross-source mutations rejected

### Phase H: Persisted Query Registry & Pre-Approval
- Query submission with developer metadata and business purpose
- Stable identifier on approval
- Approval ceiling enforcement (restrict within, reject exceed)
- Governance modes: registry-required vs pre-approved tables
- Deprecation with replacement pointer
- Registration changes flag affected entries for re-review

### Phase I: Output Formats & Arrow Flight
- Content negotiation: JSON, NDJSON, CSV, Parquet, Arrow IPC
- Arrow Flight gRPC endpoint (port 8815) with streaming record batches
- Flight SQL connector modes: `catalog` (metadata discovery), `approved` (persisted queries), default (full execution)
- Zaychik Flight SQL proxy integration for end-to-end Arrow streaming

### Phase J: Large Result Redirect
- S3-compatible blob storage redirect with presigned URLs
- Threshold-based conditional redirect
- Trino CTAS for Parquet/ORC (data never passes through Provisa)
- Multi-root query support (some fields inline, some redirected)
- Pre-approved tables cannot use redirect

### Phase K: Admin API (Strawberry)
- Strawberry GraphQL endpoint at `/admin/graphql`
- CRUD for sources, tables, relationships, roles, RLS rules
- Schema regeneration triggered on config changes
- Config download/upload (`GET/PUT /admin/config`)

### Phase L: Connection Pooling Hardening
- PgBouncer for PostgreSQL sources
- Driver-level pooling for non-PG RDBMS
- Per-source pool sizing configuration

### Phase M: Production Infrastructure
- Helm chart for Kubernetes deployment
- Trino StatefulSet with configurable workers, HPA autoscaling

### Phase N: UI
- React app (Vite + TypeScript) with role-driven rendering
- Capability-driven views: Sources, Tables, Relationships, Security, Query Development, Approval
- GraphiQL query editor with Provisa plugin (submit, compile, redirect controls)
- GraphQL Voyager schema explorer (iframe with CDN bundle)
- Confirmation dialogs for destructive actions
- Approval queue with rejection reasons

### Phase O: Query Result Caching
- Redis-backed query result cache
- Security-partitioned cache keys (role + RLS context)
- Cache invalidation on registration changes and mutations
- `X-Provisa-Cache: HIT|MISS` response headers with age

### Phase P: Materialized View Optimization
- Transparent SQL-level MV rewrite (invisible in GraphQL SDL)
- Join pattern matching with partial match support
- Scheduled background refresh via Trino CTAS
- Stale MV bypass (no silent stale data)
- Optional SDL exposure for MVs with computed semantics
- RLS applied on MV-backed queries

### Phase Q: Column-Level Masking
- Per-column per-role data masking at SQL level
- Mask types: regex (REGEXP_REPLACE), constant (literal/NULL/MAX/MIN), truncate (DATE_TRUNC)
- Type validation (regex only on strings, NULL only on nullable)
- Masking injected into SELECT projection; WHERE uses raw values

### Phase R: LLM Relationship Discovery
- Claude API-powered FK candidate suggestion
- Scope control: per-table, per-domain, cross-domain
- Candidate lifecycle: suggested, accepted, rejected, expired
- Sample data validation for high-confidence candidates
- Admin endpoints for discovery trigger, review, accept/reject

### Phase S: gRPC Query Endpoint
- Auto-generated `.proto` schemas from registration model (per role)
- gRPC server on port 50051 with server reflection
- Streaming queries (one message per row), unary mutations
- Full security pipeline (RLS, masking, sampling, governance)
- Proto files served at `GET /data/proto/{role_id}`

### Phase T: Documentation
- README with quick start, feature overview, supported sources
- Architecture guide with request pipeline and routing decision tree
- Configuration reference (all YAML sections)
- API reference (all HTTP, Flight, gRPC endpoints)
- Security model deep dive
- Source type reference

### Phase U: API Sources (REST, GraphQL, gRPC)
- Register API endpoints as data sources with auto-discovery
- OpenAPI spec parsing, GraphQL introspection, gRPC reflection
- PG cache with TTL (endpoint > source > global)
- Primitive columns native, complex objects as JSONB
- JSONB field promotion via PG generated columns
- Stale-while-revalidate caching strategy

### Phase V: Kafka Sources & Sink
- Kafka topics as read-only tables via Trino Kafka connector
- Schema Registry integration (Avro, Protobuf, JSON Schema)
- Discriminator-based topic splitting (multiple types per physical topic)
- Default time window auto-injection (`default_window`)
- Query result publishing to Kafka topics (sink)

### Phase W: Authentication
- Pluggable auth providers: Firebase, Keycloak, OAuth 2.0/OIDC, simple (username/password)
- Superuser bootstrap access (works with any provider)
- JWT validation with JWKS rotation support
- Role mapping from identity claims to Provisa roles
- Login page with provider-specific UI

### Phase X: JDBC Arrow Flight Transport
- JDBC driver wired to Arrow Flight (`grpc://host:8815`) for streaming results
- Auto-detection with silent fallback to HTTP
- Batch-by-batch streaming (memory bounded to one record batch)
- Both `approved` and `catalog` modes supported

### Phase Y: Admin Page Global Features
- MV manager: list, enable/disable, manual refresh, error display
- Global cache controls: stats, purge all, purge by table
- System health panel: Trino, PG pool, Redis status
- Scheduled task overview with enable/disable toggles

### Phase Z: Per-Source & Per-Table Cache Configuration
- Hierarchical TTL resolution: table > source > global default
- `cache_enabled` toggle per source (disables all child tables)
- UI display of effective (resolved) TTL with inheritance chain
- Admin mutations: `updateSourceCache`, `updateTableCache`

### Phase AA: Quick Wins (AD1-AD2 only)
- **AD1 - Naming Convention**: `none`, `snake_case`, `camelCase`, `PascalCase` at global, source, and table level; explicit alias always wins
- **AD2 - OrderBy Alignment**: `{column: direction}` format with 6-value enum (`asc`, `desc`, `asc_nulls_first`, `asc_nulls_last`, `desc_nulls_first`, `desc_nulls_last`); relationship ordering via JOIN
- Upsert mutations (`upsert_<table>`) via `INSERT ... ON CONFLICT DO UPDATE`
- `distinct_on` argument for root query fields
- Column presets: auto-inject values from headers, `now()`, or literals on insert/update
- Inherited roles with `parent_role_id` and capability flattening
- Scheduled triggers with cron expressions (APScheduler)
- Direct-route dialect expansion (ClickHouse, MariaDB, SingleStore, Redshift, Databricks, Hive, Druid, Exasol)
