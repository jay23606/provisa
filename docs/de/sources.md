# Quelltypen

## Ausführungsmodell

Jede Abfrage wird letztlich über die Federation-Engine ausgeführt, die Federation über alle Quellen hinweg bereitstellt. Quellen fallen basierend auf ihrer Konnektivität in drei Kategorien. [tool-verified: `provisa/core/models.py` lines 84–132] (REQ-550)

| Kategorie | Hat direkten Treiber | Hat föderierten Connector | Beispiele |
| --- | --- | --- | --- |
| **Direktfähig** | Ja | Ja | PostgreSQL, MySQL, MariaDB, SingleStore, SQL Server, Oracle, DuckDB |
| **Nur Federation** | Nein | Ja | Redshift, Druid, Exasol, Hive, Iceberg, Delta Lake, Hive (S3-gestützt) |
| **Direktlesen (Replikat)** | Ja | Ja | Snowflake, Databricks, ClickHouse — Treiber liest Daten und landet ein Replikat; Abfragen laufen gegen das Replikat in der aktiven Engine |
| **Direkt (kein quellenübergreifender Connector)** | Ja | Nein | Athena — Einzelquellen-Anweisungen laufen vollständig in Athena; quellenübergreifende Joins landen ein vollständiges Replikat |
| **Materialisieren → Federation** | Nein | Nein | REST/OpenAPI, Remote-GraphQL, gRPC, Neo4j Cypher, SPARQL, WebSocket, RSS, CSV, SQLite, Parquet, Ingest (Push-Empfänger), GovData, SharePoint, Salesforce, ServiceNow, Cloud-Inventar, Splunk, Qdrant, Azure Cosmos DB |

**Direktfähige** Quellen führen Einzelquellen-Abfragen über ihren nativen Treiber aus (unter 100 ms) und umgehen dabei die Federation-Engine (REQ-027, REQ-229). Sie behalten volle Connector-Unterstützung und nehmen an der Federation teil, wenn sie mit anderen Quellen gejoint werden (REQ-028).

**Nur-Federation**-Quellen werden immer über die Federation-Schicht abgefragt. Es existiert kein direkter Treiber (REQ-229).

**Direktlesen (Replikat)**-Quellen haben einen DirectDriver, der nativ aus dem Warehouse liest (wo verfügbar Arrow-nativ), ein Replikat in den Materialisierungs-Store der aktiven Engine landet, und Abfragen laufen dann gegen dieses Replikat. Siehe [Warehouses als benannte Quellen](#warehouses-as-named-sources).

**Direkt (kein quellenübergreifender Connector)**-Quellen haben einen DirectDriver, der Einzelquellen-Anweisungen vollständig in der Quelle ausführt — jeder Filter, jede Spalte und jedes Limit wird weitergereicht. Verbindet eine Anweisung die Quelle mit einer anderen, liest der Treiber die Daten und landet ein Replikat; der Join läuft gegen dieses Replikat in der aktiven Engine. Für diese Quellen existiert kein Trino-Connector.

**Materialize**-Quellen haben keinen föderierten Connector. Provisa ruft ihre Daten ab (beim Start oder zur Abfragezeit) und cacht sie als Parquet in S3 oder in PostgreSQL, wodurch sie für quellenübergreifende Abfragen durch die Federation-Engine erreichbar werden (REQ-309).

---

## Alle Quellen

Provisa registriert **65** Quelltypen, die das Sources-Formular anbietet. Die folgenden Tabellen decken alle 65 ab; der Index ist die Zählung. [tool-verified: `provisa-ui/src/pages/sources/constants.ts` `SOURCE_TYPES`; Kaggle, Wikipedia, GitHub und GitLab zählen als eigenständige Quellen, obwohl sie intern über die Connectors `files` und `graphql_remote` registrieren]

| # | Gruppe | Quelltypen |
| --- | --- | --- |
| 1–15 | [RDBMS](#rdbms) | `postgresql`, `mysql`, `mariadb`, `singlestore`, `sqlserver`, `oracle`, `duckdb`, `cockroachdb`, `yugabytedb`, `greenplum`, `tidb`, `firebird`, `airport`, `saphana`, `hiveserver2` |
| 16–23 | [Cloud-Data-Warehouses](#cloud-data-warehouses) | `snowflake`, `bigquery`, `databricks`, `redshift`, `athena`, `fabric`, `synapse`, `trino` |
| 24–28 | [Analytics / OLAP](#analytics-olap) | `clickhouse`, `druid`, `exasol`, `elasticsearch`, `pinot` |
| 29–32 | [Data-Lake / offene Tabellenformate](#data-lake-offene-tabellenformate) | `iceberg`, `delta_lake`, `hive`, `hive_s3` |
| 33–37 | [NoSQL](#nosql) | `mongodb`, `cosmosdb`, `qdrant`, `cassandra`, `redis` |
| 38–40 | [Streaming](#streaming) | `kafka`, `websocket`, `rss` |
| 41 | [Push-Empfänger](#push-empfänger) | `ingest` |
| 42–43 | [Graph & Semantic](#graph-semantic) | `neo4j`, `sparql` |
| 44–47 | [Dateibasiert](#dateibasiert) | `sqlite`, `csv`, `parquet`, `files` |
| 48–49 | [Observability & Sonstiges](#observability-sonstiges) | `google_sheets`, `prometheus` |
| 50–54 | [Enterprise-SaaS](#enterprise-saas-connectors) | `sharepoint`, `salesforce`, `servicenow`, `cloudops`, `splunk` |
| 55–59 | [API-Quellen](#api-quellen) | `openapi`, `graphql_remote`, `grpc_remote`, GitHub, GitLab |
| 60 | [GovData](#govdata) | `govdata` |
| 61–62 | [Data-Quality-Checker](#data-quality-checkers-req-1443) | `soda`, `great_expectations` |
| 63 | [Data-Profiler](#data-profiler) | `data_profiler` |
| 64 | [Kaggle-Datasets](#kaggle-datasets) | Kaggle (über das Sources-Formular bereitgestellt; registriert als `files`-Quelle — siehe [Kaggle-Datasets](#kaggle-datasets)) |
| 65 | [Wikipedia](#wikipedia) | Wikipedia (registriert als `files`-Quelle, die die benannten Seiten crawlt — siehe [Wikipedia](#wikipedia)) |

Referenz für jeden Quelltyp, den Provisa unterstützt. „Direkter Treiber" bedeutet, dass Einzelquellen-Abfragen nativ gegen die Quelle ausgeführt werden (unter 100 ms) (REQ-027). „Connector-Name" ist der föderierte Connector, der verwendet wird, wenn die Quelle an Mehrquellen-JOINs teilnimmt (REQ-028). [tool-verified: `provisa/core/source_registry.py` `SOURCE_TO_DIALECT`; `provisa/federation/trino_connectors.py` `trino_connector_name`]

### RDBMS

| Quelltyp | Direkter Treiber | Connector-Name | Dialekt | Mutations |
| ------------ | -------------- | ----------------- | ----------------- | ----------- |
| `postgresql` | asyncpg | postgresql | postgres | Ja |
| `mysql` | aiomysql | mysql | mysql | Ja |
| `mariadb` | aiomysql | mariadb | mysql | Ja |
| `singlestore` | — | singlestore | singlestore | Federiert |
| `sqlserver` | aioodbc | sqlserver | tsql | Ja |
| `oracle` | oracledb | oracle | oracle | Ja |
| `duckdb` | duckdb | memory | duckdb | Ja |
| `cockroachdb` | asyncpg (pg wire) | postgresql | postgres | Ja |
| `yugabytedb` | asyncpg (pg wire) | postgresql | postgres | Ja |
| `greenplum` | asyncpg (pg wire) | postgresql | postgres | Ja |
| `tidb` | aiomysql (mysql wire) | mysql | mysql | Ja |
| `firebird` | — | — (DuckDB-Erweiterung) | — | Nein |
| `airport` | — | — (DuckDB-Erweiterung) | — | Nein |
| `saphana` | SQLAlchemy (`hana+hdbcli`) | — | — | Nein |
| `hiveserver2` | impyla (HiveServer2 über Thrift) | — | hive | Nein |

Wire-kompatible Datenbanken verwenden den JDBC-Treiber, den nativen Async-Treiber und den Dialekt eines Basis-Wire-Protokolls wieder — CockroachDB, YugabyteDB und Greenplum reiten auf dem PostgreSQL-Wire; TiDB reitet auf dem MySQL-Wire. Sie benötigen nur Registry-Einträge, keinen neuen Connector-Code. [tool-verified: `provisa/core/source_registry.py` `_PG_WIRE_TYPES`, `_MYSQL_WIRE_TYPES`] (REQ-950)

`firebird` (Firebird 3/4/5) und `airport` (Arrow-Flight-Server) sind registrierte Quelltypen, die vor Ort über DuckDB-Community-Erweiterungen erreicht werden, wenn DuckDB die aktive Engine ist — kein direkter Treiber, kein föderierter Connector. [tool-verified: `provisa/core/models.py` lines 44, 93] (REQ-899)

#### `saphana`

SAP HANA wird über einen eigenen Treiber gelesen und in den Store der aktiven Engine repliziert, ist also auf jeder Engine erreichbar. Das Formular verlangt Host, Port (Standard 39015), Benutzername, Passwort und Datenbank; bei einem Multi-Tenant-System benennt die Datenbank den Tenant. Register Table listet die Schemas auf, die der Benutzer lesen darf; die Systemschemas von HANA bleiben außen vor. [tool-verified: `provisa/executor/drivers/registry.py` `_SQLALCHEMY_FALLBACK`; `provisa/api/admin/introspect.py` `_SAPHANA_SYSTEM_SCHEMAS`] (REQ-1753)

#### `hiveserver2`

Ein HiveServer2-Endpunkt, direkt über Thrift gelesen, für ein Hive-Deployment, in dem nur dieser Endpunkt erreichbar ist. Er ist von `hive` und `hive_s3` zu unterscheiden, die die Dateien und den Metastore des Warehouse lesen und nie über HiveServer2 laufen. Zeilen werden über den Endpunkt gelesen und in den Store der aktiven Engine repliziert. Das Formular verlangt Host, Port (Standard 10000), Benutzername, Passwort und Datenbank; `federation_hints.auth_mechanism` wählt die Authentifizierung (Standard `PLAIN`, zum Beispiel `GSSAPI` für Kerberos). [tool-verified: `provisa/executor/drivers/hive.py` `HiveDriver`; `provisa/core/models.py` `SourceType.hiveserver2`] (REQ-1731)

### Cloud-Data-Warehouses

[tool-verified: `executor/drivers/snowflake.py`, `executor/drivers/databricks.py`, `executor/drivers/registry.py`]

| Quelltyp | Direkter Treiber | Connector-Name | Dialekt | Mutations | Hinweise |
| ------------ | -------------- | ----------------- | ----------------- | ----------- | ------- |
| `snowflake` | SnowflakeDriver | snowflake | snowflake | Federiert | Liest über snowflake-connector-python; landet Replikat; `account`/`warehouse`/`role` in `federation_hints` (REQ-988) |
| `bigquery` | — | bigquery | bigquery | Federiert | Kein DirectDriver; erreicht über Federation-Engine oder BigQuery-Engine-ATTACH |
| `databricks` | DatabricksDriver | delta_lake | databricks | Federiert | Liest über databricks-sql-connector (Cloud Fetch, Arrow); landet Replikat; `http_path` erforderlich in `federation_hints` (REQ-987) |
| `redshift` | — | redshift | redshift | Federiert | — |
| `athena` | AthenaDriver | — | athena | Partiell (INSERT immer; UPDATE/DELETE/MERGE nur für Iceberg) | Serverless-S3-Abfrage; Einzelquellen-Anweisungen laufen vollständig in Athena; quellenübergreifende Abfragen landen ein Replikat; `region` in `federation_hints` erforderlich (REQ-1981) |
| `fabric` | MssqlWarehouseDriver | — | tsql | Federiert | Microsoft Fabric Warehouse; T-SQL über TDS, Azure-AD-Auth; landet Replikat (REQ-995) |
| `synapse` | MssqlWarehouseDriver | — | tsql | Federiert | Azure Synapse SQL; T-SQL über TDS, Azure-AD-Auth; landet Replikat (REQ-995) |
| `trino` | SQLAlchemyDriver | — | — | Federiert | Entfernter Trino-/Presto-Koordinator, gelesen über den SQLAlchemy-Trino-Dialekt; landet Replikat auf jeder Engine (REQ-994) |

#### `athena`

Amazon Athena ist ein serverloser Abfragedienst für Daten in S3, abgerechnet pro gelesenes Byte. Eine Anweisung ausschließlich auf Athena-Tabellen wird direkt in Athena ausgeführt: Filter, Spaltenlisten und `LIMIT` werden vollständig übergeben, sodass nur die Bytes gescannt und abgerechnet werden, die Athena zur Beantwortung benötigt. Eine Anweisung, die eine Athena-Tabelle mit einer anderen Quelle verbindet, landet zuerst ein vollständiges Replikat aus Athena — die gesamte Tabelle wird gelesen und Athena rechnet sie ab —, dann läuft der Join gegen dieses Replikat. Die Replikations- und Lastschutzeinstellungen der Quelle regeln, wie oft eine Landung stattfindet; der Docs-Hinweis ist die einzige Regel. (REQ-1981)

**Discovery.** Register Table ruft die Metadata-API von Athena auf — `ListDatabases`, `ListTableMetadata`, `GetTableMetadata`. Diese Aufrufe führen keine Abfrage aus, sodass das Auflisten von Datenbanken und Tabellen sowie das Lesen der Spalten einer Tabelle keine Bytes kostet. Die Spalten einer Tabelle werden erst gelesen, wenn die Tabelle ausgewählt wird. Partitionsschlüssel folgen den regulären Spalten. Typen werden über den Eintrag `athena` in `provisa/core/ir_types.py` zugeordnet: `array<…>`, `map<…>` und `struct<…>` werden zu `text`; ein unbekannter Typ wird unter Nennung seines Namens abgelehnt. [tool-verified: `provisa/federation/athena.py` `databases`, `tables`, `columns`; `provisa/core/ir_types.py` Eintrag `"athena"`]

**Quellfelder.**

| Feld | Wo | Erforderlich | Standard | Hinweise |
| --- | --- | --- | --- | --- |
| `database` | Quelle | Ja | — | Die standardmäßig abgefragte Glue-Datenbank |
| `username` | Quelle | Nein | — | AWS-Zugriffsschlüssel-ID; kann `${secret:…}` oder `${env:…}` sein |
| `password` | Quelle | Nein | — | Geheimer AWS-Zugriffsschlüssel; kann `${secret:…}` oder `${env:…}` sein |
| `region` | `federation_hints` | Ja | — | AWS-Region, z.B. `us-east-1` |
| `workgroup` | `federation_hints` | Nein | `primary` | Athena-Arbeitsgruppe |
| `s3_staging_dir` | `federation_hints` | Nein | Workgroup-Standard | Wo Athena Abfrageergebnisse schreibt; erforderlich, wenn die Arbeitsgruppe keinen Ort festlegt |
| `catalog` | `federation_hints` | Nein | `AwsDataCatalog` | Athena-Datenkatalog |
| `role_arn` | `federation_hints` | Nein | — | IAM-Rollen-ARN, der für jeden Aufruf übernommen wird |

Wenn sowohl `username` als auch `password` leer sind, wird die Credential-Chain von boto3 verwendet: Instanzrolle, Umgebungsvariablen (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) oder ein benanntes Profil. Eines ohne das andere wird abgelehnt. [tool-verified: `provisa/executor/drivers/athena.py` `AthenaDriver.connect`; `provisa/federation/athena.py` `athena_client`]

**Schreiboperationen.** Jede registrierte Tabelle akzeptiert `INSERT`. `UPDATE`, `DELETE` und `MERGE` sind nur für Iceberg-Tabellen verfügbar; das Format wird bei der Registrierung gespeichert (`registered_tables.table_format`). Eine Schreiboperation auf einer Hive-Tabelle, die `UPDATE`, `DELETE` oder `MERGE` anfordert, wird unter Nennung der Tabelle und der Operation abgelehnt. Athena gibt keine geschriebenen Zeilen zurück — eine `RETURNING`-Klausel wird abgelehnt, und GraphQL bietet für diese Tabellen keine Mutation-Felder; `INSERT`, `UPDATE`, `DELETE` und `COPY` sind die Schreibpfade. `INSERT … ON CONFLICT`, `UPDATE … FROM`, `DELETE … USING` und `TRUNCATE` werden unter Nennung der Form abgelehnt. [tool-verified: `provisa/executor/write_capability.py` `table_write_ops`; `provisa/executor/writable.py` `_TYPE_RETURNS_NO_ROWS`, `_TYPE_REFUSED_FORMS`]

```yaml
- id: analytics-athena
  type: athena
  database: my_glue_database
  username: ${env:ATHENA_ACCESS_KEY_ID}
  password: ${env:ATHENA_SECRET_ACCESS_KEY}
  federation_hints:
    region: us-east-1
    workgroup: primary
    s3_staging_dir: s3://my-bucket/athena-results/
```

Mit einer pro Aufruf übernommenen Rolle (Credential-Chain für die Basis-Sitzung):

```yaml
- id: analytics-athena
  type: athena
  database: my_glue_database
  federation_hints:
    region: us-east-1
    role_arn: arn:aws:iam::123456789012:role/AthenaQueryRole
    s3_staging_dir: s3://my-bucket/athena-results/
```

### Analytics / OLAP

[tool-verified: `executor/drivers/clickhouse.py`]

| Quelltyp | Direkter Treiber | Connector-Name | Dialekt | Mutations | Hinweise |
| ------------ | -------------- | ----------------- | ----------------- | ----------- | ------- |
| `clickhouse` | ClickHouseDriver | clickhouse | clickhouse | Federiert | Liest über clickhouse-connect (HTTP); `secure: "true"` in `federation_hints` für TLS (REQ-986) |
| `druid` | — | druid | druid | Nein | — |
| `exasol` | — | exasol | exasol | Nein | — |
| `elasticsearch` | HTTP (native Engines) | elasticsearch (Trino) | — | Nein | Auf Trino liest der Connector sie, seine Eigenschaften aus der Mapping-DSL des Typs [tool-verified: `trino_connectors.py:309`]; auf jeder anderen Engine liest Provisa den Index über HTTP (Indizes und Mapping für Register Table, ein Scroll-Read zum Landen) und landet die Zeilen [tool-verified: `provisa/elasticsearch/fetch.py`, `provisa/events/source_loader.py` `make_elasticsearch_loader`] (REQ-1672) |
| `pinot` | — | pinot | — | Nein | Trino-`pinot`-Connector; `pinot.controller-urls` = Host:Port des Pinot-Controllers [tool-verified: `trino_connectors.py:199`] |

### Data-Lake / offene Tabellenformate

Diese Quelltypen sind nur-Federation — kein direkter Treiber, kein Dialekt. [tool-verified: `LAKE_ONLY_SOURCES` in `provisa/core/source_registry.py`] (REQ-229)

| Quelltyp | Connector-Name | Time Travel | Hinweise |
| ------------ | ----------------- | ------------- | ------- |
| `iceberg` | iceberg | Ja (`as_of`-Argument, REQ-372) | — |
| `delta_lake` | delta_lake | Ja (`as_of`-Argument, REQ-372) | — |
| `hive` | hive | Nein | — |
| `hudi` | — (ClickHouse-`Hudi`-Engine, Zero-Copy — REQ-1178) | Nein | Kein föderierter Connector; wird vor Ort erreicht, wenn ClickHouse die aktive Engine ist |
| `hive_s3` | hive | Nein | S3-gestütztes Hive |

### NoSQL

`mongodb`, `cassandra` und `redis` haben Trino-Connectors (`redis` baut seine Eigenschaften aus der Mapping-DSL des Typs). [tool-verified: `provisa/federation/trino_connectors.py`; `provisa/core/models.py`] (REQ-017, REQ-1097)

| Quelltyp | Connector-Name | Mutations |
| ------------ | ----------------- | ----------- |
| `mongodb` | mongodb | Nein |
| `cassandra` | cassandra (Trino); CQL-Read über cassandra-driver auf jeder anderen Engine | Nein | Keyspaces sind Schemas; Register Table listet die Tabellen eines Keyspace und typisiert Spalten aus den Schema-Metadaten des Clusters (Partition Keys als Primärschlüssel); das `cassandra`-Extra installiert den Treiber [tool-verified: `provisa/cassandra/fetch.py`] (REQ-1676) |
| `redis` | redis (Trino); HTTP-freier redis-py-Read auf jeder anderen Engine | Nein | Ein Key-Präfix `<table>:*` ist eine Tabelle, und ein Hash ist eine Zeile; Register Table listet die vorhandenen Präfixe und typisiert die Spalten eines Präfixes aus dessen Hashes (ein `mapping.tables`-Eintrag überschreibt Muster, Key-Spalte, Werttyp und Spalten) [tool-verified: `provisa/redis/fetch.py`] (REQ-1675) |

### Qdrant

`qdrant` (REQ-1983) wird vom eigenen Client von Qdrant gelesen, `qdrant-client`; keine Federation-Engine hat einen Qdrant-Connector, daher wird es auf jeder Engine auf dieselbe Weise gelesen und landet dort, wo eine Anweisung es verbindet. [tool-verified: `provisa/qdrant/fetch.py`; `provisa/federation/strategy.py` `_MATERIALIZE_ONLY`]

**Verbindung.** `host` ist die URL der Instanz mit Port (`https://<cluster>.cloud.qdrant.io:6333` oder ein selbst gehostetes `http://qdrant:6333`); `password` ist ihr API-Schlüssel, eine Secret-Referenz, die beim Lesen der Quelle aufgelöst wird, leer bei einer Instanz ohne Schlüssel. `federation_hints.prefer_grpc: true` liest über den gRPC-Port von Qdrant statt über REST. Die Quelle hat ein Schema, `default`. [tool-verified: `provisa/qdrant/fetch.py` `QdrantConnection.from_source`; `provisa/qdrant/introspect.py` `SCHEMA`]

**Collection-Tabellen.** Eine Collection ist eine Tabelle, vollständig als Replikat gelandet (Scroll, Seite für Seite) und mit ihrer TTL aktualisiert; Qdrant hat keinen Change Feed. Register Table bietet die Spalten der Collection an: `id` (die Point-ID, ihr Schlüssel, Pfad `@id`), die Felder des Payloads (ein indiziertes Feld nach seinem Index typisiert, jedes andere so, wie die Stichproben-Points es nahelegen; verschachtelte Felder mit ihrem Pfad abgeflacht) und eine `json`-Spalte je Vektor (Pfad `@vector`, bei einem benannten Vektor `@vector.<name>`), nicht ausgewählt angeboten. Ein Keyed Read auf `id` ist ein `retrieve`; auf ein Payload-Feld ein gefilterter Scroll. [tool-verified: `provisa/qdrant/introspect.py` `columns`; `provisa/qdrant/loader.py`]

**Suchtabellen.** Die Vektorsuche ist eine Suchtabelle: Ihr `query_template` enthält eine Query-API-Anfrage.

```json
{"collection": "docs", "query": "@query_vector", "using": "text",
 "filter": {"must": [{"key": "lang", "match": {"value": "@lang"}}]},
 "limit": "@k", "score_threshold": 0.5, "model": "text-embedding-3-small"}
```

- `query` ist immer ein Argument; `using`, `filter`, `limit`, `score_threshold` und `model` sind optional. Jeder Wert in `using`, `filter`, `limit` oder `score_threshold`, der genau `"@name"` lautet, ist ebenfalls ein Argument.
- Jedes Argument ist ein Parameter der Tabelle (`query_arg`, REQ-1986), streng in seinen deklarierten Typ umgewandelt und als JSON-Wert in die Anfrage eingesetzt, nie in deren Text. Das Argument von `query` ist `array(double)` und erforderlich.
- Ein Aufrufer übergibt Argumente wie jeden Parameter: `SELECT id, score, title FROM docs_search WHERE _nf_query_vector = '[0.1, 0.2, …]' AND _nf_lang = 'en'` in SQL, Feldargumente in GraphQL.
- Ein nicht übergebenes optionales Argument filtert nichts: Seine Bedingung entfällt im Filter. Ohne `limit` liefert eine Suche den Standard von Qdrant, 10 Points.
- Der Filter wird von Qdrant angewendet, bevor die nächsten Points gewählt werden, ist also exakt. Jede andere Bedingung der Anweisung schränkt die Points, die die Suche geliefert hat, erst danach ein; sie holt keine weiteren.
- `score` ist die eigene Metrik der Collection für den durchsuchten Vektor: bei einer Cosine-Collection die Kosinus-Ähnlichkeit. Register Table listet die Vektoren der Collection mit Größe und Distanz.
- `model` nennt ein registriertes Embedding-Modell (`vector_models`, Admin → AI Models). Ein für die Abfrage übergebener Text wird dann von diesem Modell eingebettet, und ein übergebener Vektor muss die Dimensionen dieses Modells haben (REQ-429, REQ-430). Ohne `model` muss die Abfrage ein Vektor sein.

Eine Suche wird pro Anweisung unter ihren Argumenten gelesen, ihre Zeilen für die TTL der Tabelle unter diesen Argumenten gehalten. `cosine_similarity(column, vector)` (REQ-423) wird für Qdrant nicht übersetzt: Eine Ähnlichkeitssuche ist eine Suchtabelle. Schreibzugriffe auf Qdrant werden nicht unterstützt. [tool-verified: `provisa/qdrant/table.py` `check_table`, `plan`, `read`; `provisa/api/data/materialization.py` `_is_native_read`]

### Streaming

| Quelltyp | Mechanismus | Mutations |
| ------------ | ----------- | ----------- |
| `kafka` | Föderierter Kafka-Connector; Schema über Confluent Schema Registry (Avro, Protobuf, JSON Schema), manuelle Definition oder Stichproben-Inferenz (REQ-147, REQ-150) | Nur Sink (REQ-176) |
| `websocket` | Externer WebSocket-Feed — verbinden, abonnieren, Ereignisse empfangen; Ergebnisse materialisiert (REQ-338) | Nein |
| `rss` | RSS-2.0-/Atom-Feed — pollen, Watermark nach pubDate/updated; Ergebnisse materialisiert (REQ-342, REQ-343) | Nein |

### Push-Empfänger {: #push-empfänger }

| Quelltyp | Mechanismus | Mutations |
| ------------ | ----------- | ----------- |
| `ingest` | Externe Dienste POSTen JSON-Ereignisse; Ergebnisse materialisiert (REQ-331, REQ-335) | Nein |

### Graph & Semantic

| Quelltyp | Mechanismus | Mutations |
| ------------ | ----------- | ----------- |
| `neo4j` | Cypher über HTTP-API, Ergebnisse in PostgreSQL gecacht (REQ-295) | Nein |
| `sparql` | SPARQL-1.1-POST, Ergebnisse in PostgreSQL gecacht (REQ-297) | Nein |

### Dateibasiert

Zwei Mechanismen decken Dateien ab. Beide verwenden das Feld `path` statt `host`/`port`. [tool-verified: `provisa/core/models.py`] (REQ-553)

**Einzeldatei-Quellen** — `sqlite`, `csv`, `parquet` richten `path` auf eine Datei.

| Quelltyp | Transporte | Mutations |
| --- | --- | --- |
| `sqlite` | lokal | Ja |
| `csv` | lokal | Nein |
| `parquet` | lokal, `s3://` | Nein |

Private Buckets benötigen Zugangsdaten (AWS-Region und Keys aus der Umgebung). Für CSV über `s3://` oder `http(s)://`, oder um viele Dateien auf einmal zu registrieren, verwenden Sie die `files`-Quelle. [tool-verified: `provisa/file_source/source.py`]

**`files`-Quelle** — richtet `path` auf ein Glob-Muster, durchläuft es rekursiv und registriert das Verzeichnis als föderierten Katalog von Tabellen. Sie liest viele Formate über viele Transporte; die untenstehenden Mengen stammen vom File-Connector (kenstott/calcite-Fork). [tool-verified: `provisa/core/catalog.py` `files` branch and `provisa/core/models.py` `SOURCE_TO_CONNECTOR`; Format- und Transportlisten vom Calcite-`file`-Adapter — `FileSchema.java`, `storage/StorageProviderFactory.java`]

| Formate | Transporte |
| --- | --- |
| CSV, TSV, JSON, YAML, Excel (XLS/XLSX), Parquet, Arrow und in Tabellen konvertierte Dokumente — HTML, Markdown, DOCX, PPTX | Lokales Dateisystem, HTTP(S), `s3://`, `hdfs://`, `ftp://`/`ftps://`, `sftp://`, `iceberg://`, SharePoint (REST und Microsoft Graph) |

```yaml
- id: sales_files
  type: files
  path: s3://bucket/sales/**/*.csv   # glob; local and http(s):// also supported
```

Jede `files`-Quelle kann in ihrem Mapping auch ein `crawl` deklarieren, mit denselben Einstellungen, die unter [Wikipedia](#wikipedia) aufgeführt sind: Die Quelle liest dann zuerst Webseiten und landet jede HTML-Datentabelle und jede verlinkte Datendatei in ihrem Verzeichnis als Tabelle. [tool-verified: `provisa/file_source/crawl.py` `crawl_operand`]

Auf der DuckDB-Engine wird `files` nativ gelesen — eine `read_csv_auto`-Scanner-View pro `<table>.csv` unter dem aufgelösten Verzeichnis (REQ-229) [tool-verified: `provisa/federation/connector_duckdb.py` `DuckDBFilesConnector`]. Auf einer Engine ohne eigenen `files`-Connector landen Zeilen über denselben connector-gebündelten Calcite-pgwire-Server (`pgwire-file`), den auch sharepoint/splunk verwenden (REQ-954) — siehe [Enterprise-SaaS-Connectors](#enterprise-saas-connectors) unten. Die End-to-End-UI-Abdeckung (Sources-Formular → Register Table → SQL-Abfrage) und der pgwire-Landepfad sind in REQ-1694 nachgewiesen.

#### Kaggle-Datasets (REQ-1780, REQ-1781, REQ-1782, REQ-1783) {: #kaggle-datasets }

Kaggle ist eine Datei-Download-Plattform. Ein bereitgestellter Kaggle-Datensatz registriert sich als Quelle vom Typ `files` und wird über denselben pgwire-file-Connector abgefragt, den jede andere `files`-Quelle verwendet — es gibt keinen `kaggle`-SourceType im Enum. [tool-verified: `provisa/kaggle/downloader.py`; `provisa/core/models.py` `SourceType` — kein `kaggle`-Literal]

**Einen Datensatz hinzufügen.** Öffnen Sie Sources → Subscriptions → Kaggle. Das Formular durchläuft zwei sequenzielle Schritte, da Kaggles eigener Dataset-Suchendpunkt Auth erfordert — die Auswahl kann nicht erscheinen, bevor das Token validiert ist. [tool-verified: `provisa-ui/src/pages/sources/KaggleFormSection.tsx`] (REQ-1783)

1. **Token** — geben Sie ein Kaggle-API-Token ein und klicken Sie auf „Validate". Die Validierung ruft `POST https://www.kaggle.com/api/v1/datasets/create/new` mit leerem Body auf. Ein `401` bedeutet ungültig; jede andere Antwort bedeutet gültig (Kaggles eigene Payload-Validierung greift, bevor irgendein Datensatz erstellt wird — nichts wird persistiert). [tool-verified: `provisa/kaggle/client.py` `validate_token`] (REQ-1782)
2. **Auswahl** — ein Live-Search-as-you-type-Feld fragt `GET /api/v1/datasets/list` ab. Jedes Ergebnis zeigt Dataset-Titel und -Beschreibung. Wählen Sie eines aus und klicken Sie auf „Add Dataset".

Ein Klick auf „Add Dataset" lädt das Bundle von `GET /api/v1/datasets/download/{owner}/{ref}` herunter, entpackt CSV- und Parquet-Mitglieder nach `<PROVISA_DATA_DIR>/kaggle/<owner>/<ref>/<file-stem>/<file-name>` und erstellt **eine** Quelle vom Typ `files`, deren `path` dieses Wurzelverzeichnis ist. Das Token wird serverseitig nie gespeichert. [tool-verified: `provisa/kaggle/downloader.py` `stage_dataset`; `provisa-ui/src/pages/sources/KaggleFormSection.tsx` `handleConfirmDataset`] (REQ-1780, REQ-1781)

Nach dem Hinzufügen der Quelle registrieren Sie deren Tabellen über den normalen Register-Table-Bildschirm. Die rekursive Verzeichniserkennung des pgwire-file-Connectors listet jede Datei als eigene Tabelle — derselbe Mechanismus, den jede andere `files`-Quelle verwendet (REQ-1690). (REQ-1783)

**v1-Einschränkung.** Ein Bundle mit einer `.sqlite`- oder `.db`-Datei wird rundweg mit einer klaren Fehlermeldung abgelehnt. Nur CSV- und Parquet-Dateien werden bereitgestellt. [tool-verified: `provisa/kaggle/downloader.py` `UnsupportedKaggleDataset`, `_UNSUPPORTED_EXTENSIONS`]

**Tabellenbenennung.** Eine gecrawlte Tabelle heißt `<page>__<name>`: der Titel der Seite, dann die Beschriftung der Tabelle oder, wenn sie keine hat, die letzte Überschrift über der Tabelle, beides in der Spaltennamen-Schreibweise der Quelle. Zum Beispiel ist die Tabelle unter der Überschrift „Tallest buildings in the world" auf der Seite `List_of_tallest_buildings` die Tabelle `list_of_tallest_buildings__tallest_buildings_in_the_world`. Eine verlinkte Datendatei behält ihren eigenen Namen. [tool-verified: a live crawl of that page through the 0.109.0 file bundle]

**Aktualisieren.** Um einen Datensatz erneut abzurufen, nachdem Kaggle eine neue Version veröffentlicht hat, rufen Sie die GraphQL-Mutation `refreshKaggleSource` mit der Quell-ID und einem gültigen Token auf. Dies stellt die Dateien vor Ort erneut bereit und leert den pgwire-file-Endpunkt-Cache, sodass der Connector bei seiner nächsten Abfrage etwaige Schemaänderungen übernimmt. Die zur Erstellungszeit in `federation_hints` gespeicherten `kaggle_owner` und `kaggle_ref` identifizieren, welcher Datensatz erneut abgerufen werden soll. [tool-verified: `provisa/api/admin/schema_mutation.py` `refresh_kaggle_source`] (REQ-1780)

**Kein statischer YAML-Konfigurationspfad.** Kaggle-Quellen werden nur über das Sources-Formular erstellt. Eine nach YAML exportierte Kaggle-Quelle erscheint als `type: files` mit `kaggle_owner` und `kaggle_ref` in `federation_hints`. Ein erneuter Download von Kaggle erfordert den UI-Refresh-Flow oder die Mutation `refreshKaggleSource` — das Ausrichten des YAML-`path` auf ein vorab bereitgestelltes Verzeichnis ist die Alternative für air-gapped Umgebungen.


#### Wikipedia (REQ-1960) {: #wikipedia }

Wikipedia crawlt die Seiten, die Sie benennen. Jede Datentabelle einer Seite und jede verlinkte CSV-, TSV-, Excel-, JSON- oder Parquet-Datei wird zu einer Tabelle der Quelle. Wie Kaggle registriert es sich als `files`-Quelle mit einem `crawl` in ihrem Mapping. Das Hinzufügen registriert nichts: Ein Steward registriert die gewünschten Tabellen über den normalen Register-Table-Bildschirm. [tool-verified: `provisa/file_source/wikipedia.py` `crawl_settings`, `DATA_FILE_EXTENSIONS`; `provisa-ui/src/pages/sources/constants.ts` `wikipedia: "files"`] (REQ-316)

**Einrichtungsfelder.**

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| Pages to start from | keiner (erforderlich) | Eine pro Zeile: ein Seitentitel oder die Adresse einer Seite in der gewählten Ausgabe |
| Language edition | `en` | Der Code der Ausgabe, zum Beispiel `en`, `de` oder `ja` |
| Link depth | `1` | Wie viele Links von einer Startseite entfernt gelesen wird; `0` liest nur die Startseiten |
| Page limit | `25` | Die meisten Seiten, die ein Crawl liest |
| Contact | leer | Wird mit jeder Anfrage gesendet, damit Wikipedia Sie erreichen kann, wie seine Richtlinie es verlangt |
| Follow "See also" links | aus | Aus lässt diesen Abschnitt aus dem Artikel weg |
| What this edition calls its "See also" section | leer | Wird nur gefragt, wenn das Feld darüber aus ist und Provisa den Abschnitt für die gewählte Ausgabe nicht benennen kann. Der Titel des Abschnitts, wie eine Seite ihn zeigt, zum Beispiel `Voir aussi` |
| Directory for the crawl's files | leer | Wohin Tabellen und Datendateien geschrieben werden. Leer: `<PROVISA_DATA_DIR>/crawl/<source id>` |

[tool-verified: `provisa-ui/src/pages/sources/WikipediaFields.tsx`; `provisa-ui/src/i18n/locales/en/sourceFormFieldsExtended.json` `wp*`; `provisa/file_source/wikipedia.py` `DEFAULTS`; `provisa/file_source/crawl.py` `crawl_landing_directory`]

Provisa kennt die Überschrift „See also" dieser Ausgaben: `en`, `de`, `es`, `it`, `pt`, `nl`, `pl`, `sv`, `ja`, `zh`, `ru`. Bei jeder anderen Ausgabe fragt das Formular, wenn „See also" aus ist, wie die Ausgabe diesen Abschnitt nennt; geben Sie seinen Titel ein, wie eine Seite ihn zeigt (zum Beispiel `Voir aussi`). Eine Quelle, die ohne ihn gespeichert wird, wird abgelehnt (`wikipedia.see_also_heading_needed`). [tool-verified: `provisa/file_source/wikipedia.py` `SEE_ALSO_HEADING`, `crawl_settings`]

**Welche Links verfolgt werden.** Ein Link wird danach gewählt, was das Markup der Seite selbst über ihn sagt, nie nach einem Namen in seiner Adresse: Solche Namen unterscheiden sich in jeder Sprachausgabe und kommen auch in gewöhnlichen Titeln vor. [tool-verified: `provisa/file_source/wikipedia.py` module docstring]

- Verfolgt: Links auf andere Artikel, die im Fließtext, in Listen und in Datentabellen des Artikels stehen. Die Markup-Markierung ist `a[rel='mw:WikiLink']`.
- Nicht verfolgt: noch nicht geschriebene Seiten, die Seite selbst, Buchquellen-Nachschläge, Dateiseiten, andere Wikis und externe Sites.
- Gar nicht gelesen (entfernt, bevor Links und Tabellen gesammelt werden): Navigationskästen, Infoboxen, Anmerkungen und Belege, Kategorien, das Inhaltsverzeichnis, Bilder und Wartungshinweise.
- Nicht gelesen, solange Sie die Option nicht einschalten: der Abschnitt „See also".

Nur Tabellen, die Redakteure als Datentabellen markieren (`table.wikitable`), werden zu Tabellen, und eine Tabelle mit weniger als 2 Zeilen wird nicht angeboten. [tool-verified: `provisa/file_source/wikipedia.py` `LINK_SELECTOR`, `REMOVE_SELECTORS`, `TABLE_SELECTOR`, `DEFAULTS`]

**Erweiterte Crawl-Einstellungen.** Das Formular hält diese unter „Crawl settings" eingeklappt und zeigt jede mit ihrem Standard; lassen Sie ein Feld leer, um den Standard zu behalten. In einem `files`-Mapping stehen dieselben Namen unter `crawl:`, und ein Name außerhalb dieser Liste wird abgelehnt. [tool-verified: `provisa/file_source/crawl.py` `CRAWL_SETTINGS`, `crawl_operand`; `provisa/file_source/wikipedia.py` `crawl_settings`]

| Einstellung | Wikipedia-Standard | Bedeutung |
| --- | --- | --- |
| `start_urls` | die Seiten, die Sie benannt haben | Seiten, bei denen der Crawl beginnt |
| `max_depth` | `1` | Linktiefe |
| `max_pages` | `25` | Seitenlimit |
| `request_delay` | `1 seconds` | Pause zwischen Anfragen |
| `user_agent` | `Provisa/<version> (+https://provisa.dev) file-crawler`, mit angehängtem Kontakt | Der Name, den sich der Crawl gibt |
| `content_selector` | `#mw-content-text .mw-parser-output` | CSS-Selektor: Links und Tabellen werden nur darin gelesen |
| `remove_selectors` | die Liste der oben beschriebenen Teile | CSS-Selektoren für ausgelassene Teile. Wer sie angibt, ersetzt die ganze Liste, einschließlich der „See also"-Regel |
| `link_selector` | `a[rel='mw:WikiLink']` mit Ausschlüssen | CSS-Selektor, dem ein Link entsprechen muss, um verfolgt zu werden |
| `link_exclude_patterns` | leer | Reguläre Ausdrücke; ein Link, dessen Adresse einen findet, wird nicht verfolgt |
| `follow_external_links` | `false` | Links auf andere Sites verfolgen |
| `allowed_domains` | nicht gesetzt | Domains, die der Crawl besuchen darf |
| `table_selector` | `table.wikitable` | CSS-Selektor, dem eine Tabelle entsprechen muss |
| `generate_tables_from_html` | nicht gesetzt | Ob HTML-Tabellen zu Tabellen werden |
| `html_table_min_rows` | `2` | Mindestzahl Zeilen einer Tabelle |
| `html_table_max_rows` | nicht gesetzt | Höchstzahl Zeilen einer Tabelle |
| `allowed_file_extensions` | `csv`, `tsv`, `xlsx`, `xls`, `json`, `parquet` | Verlinkte Dateitypen, die zu Tabellen werden |
| `html_cache_ttl` | `1 days` | Wie lange ein Crawl aufbewahrt wird |
| `max_html_size` | nicht gesetzt | Größte gelesene Seite, zum Beispiel `10MB` |
| `max_data_file_size` | nicht gesetzt | Größte gelesene Datendatei, zum Beispiel `100MB` |

**Tabellenbenennung.** Eine gecrawlte Tabelle heißt `<page>__<name>`. Der Name ist die eigene `id` der Tabelle, wenn sie eine hat, sonst ihre Beschriftung, sonst die nächste Überschrift darüber. Zum Beispiel wird eine Tabelle unter der Überschrift „Tallest buildings" auf der Seite `List_of_tallest_buildings` nach der Namensnormalisierung zu `list_of_tallest_buildings__tallest_buildings`. [tool-verified: calcite `file` adapter `HtmlToJsonConverter.java` (`baseFileName + "__" + tableName`), `HtmlTableScanner.java` `getTableName`] [inferred: the exact normalized spelling in the example]

**Aktualisieren.** Ein Crawl wird für die Cache-Dauer aufbewahrt, standardmäßig `1 days` (`html_cache_ttl`). Seiten werden erst nach Ablauf dieser Zeit erneut abgerufen. [tool-verified: `provisa/file_source/wikipedia.py` `DEFAULTS`]


### Observability & Sonstiges

`prometheus` hat einen Trino-Connector (Eigenschaften aus der Mapping-DSL des Typs gebaut). `google_sheets` ist ein registrierter Quelltyp ohne Trino-Connector und materialisiert über die API-Cache-Pipeline. [tool-verified: `provisa/federation/trino_connectors.py:314`; `provisa/core/models.py` lines 87–88]

| Quelltyp | Connector-Name | Mutations |
| ------------ | ----------------- | ----------- |
| `google_sheets` | — (materialisiert) | Nein |
| `prometheus` | prometheus | Nein | Eine Metrik ist eine Tabelle, und ein Sample ist eine Zeile (`timestamp`, `value`, eine Spalte pro Label); auf jeder Engine ohne Live-Connector liest Provisa die HTTP-API — Metriknamen und Labels für Register Table, `query_range` über den Bereich der Tabelle zum Landen [tool-verified: `provisa/prometheus/fetch.py`] (REQ-1689)

### Enterprise-SaaS-Connectors

SharePoint, Salesforce, ServiceNow, Cloud-Inventar und Splunk registrieren sich über Apache-Calcite-Connectors (kenstott/calcite-Fork). Keiner hat einen direkten Treiber — Provisa startet den mitgelieferten Calcite-pgwire-Server des Connectors (`pgwire-sharepoint`, `pgwire-salesforce`, `pgwire-servicenow`, `pgwire-cloudops`, `pgwire-splunk`) und erreicht ihn als generischen PostgreSQL-Endpunkt. Auf der DuckDB-Engine wird dieser Endpunkt live über die postgres-Erweiterung angehängt: Register Table listet die Tabellen des Connectors aus dem angehängten Katalog, Abfragen lesen den Connector vor Ort, und Filter und Projektionen werden zu Calcite heruntergeschoben (REQ-1690) [tool-verified: `provisa/federation/connector_duckdb.py` `_DuckDBPgwireConnector`]. Jede andere Engine landet die Zeilen im Materialisierungs-Store für die Federation (REQ-954). Die Bundles werden pro OS/Architektur aus dem gepinnten `kenstott/calcite`-Release abgerufen (`pgwire-<connector>-<version>-<os>-<arch>.tar.gz`; macOS arm64, Linux x86_64, Windows x86_64) [tool-verified: `provisa/runtime_deps/pgwire_bundles.py`] Ein Operator kann stattdessen pro Connector einen Bundle-Ordner benennen, der für diesen Host erstellt wurde, unter Admin → Einstellungen → Connector-Server (`connectors.<connector>.bundle_dir`); siehe [Admin](admin.md).. Alle fünf Connectors aktivieren immer Groß-/Kleinschreibung-unabhängigen Namensabgleich, entsprechend der eigenen case-insensitiven Semantik des jeweiligen Produkts (REQ-725, REQ-730). [tool-verified: `provisa/core/models.py` lines 99–100; `provisa/federation/trino_connectors.py` lines 223–286]

#### `sharepoint`

SharePoint-Listen werden als Schemas aufgezählt und als abfragbare Tabellen offengelegt (REQ-726, REQ-731). Zwei Auth-Methoden: `CLIENT_CREDENTIALS` (Standard) und zertifikatbasiert über ein PFX-Zertifikat (REQ-727). Secret-Werte in `mapping` werden über die Secrets-Engine aufgelöst, bevor sie den Connector erreichen (REQ-729). [tool-verified: `provisa/federation/trino_connectors.py` lines 230–252]

| Quellfeld | Connector-Eigenschaft | Hinweise |
| --- | --- | --- |
| `base_url` oder `host` | `site-url` | SharePoint-Site-URL |
| `username` | `client-id` | Azure-App-Client-ID |
| `password` | `client-secret` | Azure-App-Client-Secret |
| `database` | `tenant-id` | Azure-Tenant-UUID |
| `mapping.auth_type` | `auth-type` | `CLIENT_CREDENTIALS` (Standard) oder `CERTIFICATE` |
| `mapping.certificate_path` | `certificate-path` | PFX-Pfad bei `auth_type: CERTIFICATE` — muss ABSOLUT sein |
| `mapping.certificate_password` | `certificate-password` | PFX-Passwort — der Key muss vorhanden sein, leerer String bei einer passwortlosen PFX |

Zertifikats-Auth auf den Nicht-Trino-Engines trägt zwei zusätzliche Regeln, beide beim Aufbau des `model.json`-Operanden des Calcite-pgwire-Servers durchgesetzt (REQ-1693). `certificate_path` muss absolut sein: Der Server läuft mit seinem Bundle-Verzeichnis als Arbeitsverzeichnis, sodass ein relativer Pfad innerhalb des Runtime-Deps-Caches aufgelöst wird und die PFX nicht gefunden wird. `certificate_password` muss in `mapping` vorhanden sein, selbst wenn die PFX kein Passwort hat — in dem Fall ist es der leere String —, denn der Calcite-Adapter lehnt ein Null-Passwort rundweg ab, und ein fehlender Key wird als Konfigurationsfehler behandelt statt stillschweigend als leeres Passwort gelesen. Ein fehlender oder relativer Wert löst `MissingConnectorConfig` mit Nennung des Felds aus. [tool-verified: `provisa/federation/pgwire_replica.py` `_sharepoint_operand`]

Wenn der Connector `information_schema.columns` nicht offenlegt, registrieren Sie die Tabelle mit expliziten Spaltendefinitionen (aus der Microsoft-Graph-API) über die `registerTable`-Mutation (REQ-732).

```yaml
- id: hr-sharepoint
  type: sharepoint
  base_url: https://kenstott.sharepoint.com
  username: ${env:SP_CLIENT_ID}
  password: ${env:SP_CLIENT_SECRET}
  database: ${env:SP_TENANT_ID}
  mapping:
    auth_type: CLIENT_CREDENTIALS
```

Zertifikats-Auth, mit dem absoluten Pfad und dem immer vorhandenen Passwort:

```yaml
- id: hr-sharepoint
  type: sharepoint
  base_url: https://kenstott.sharepoint.com
  username: ${env:SP_CLIENT_ID}
  database: ${env:SP_TENANT_ID}
  mapping:
    auth_type: CERTIFICATE
    certificate_path: /etc/provisa/certs/sharepoint.pfx
    certificate_password: ${env:SP_CERT_PASSWORD}
```

#### `salesforce`

Jedes sObject, das die Anmeldeinformationen abfragen können, ist eine Tabelle, die der Steward registrieren kann (`Account`, `Opportunity`, benutzerdefinierte `*__c`-Objekte); nichts wird automatisch registriert (REQ-1946). Spalten und Typen stammen aus dem Describe des sObjects. Filter, Projektionen, Sortierungen und Limits werden als SOQL an Salesforce weitergegeben. [tool-verified: `provisa/federation/pgwire_replica.py` `_salesforce_operand`; `provisa/federation/trino_connectors.py` `TrinoSalesforceConnector`]

Eine Salesforce-Quelle nennt die „Meine Domäne“-Anmelde-URL der Organisation und genau einen vollständigen Satz Anmeldeinformationen, gewählt über `mapping.auth_type`. Die Anmelde-URL ist die vollständige `https://…`-URL (zum Beispiel `https://acme.my.salesforce.com`); ein bloßer Host oder ein anderes Schema wird abgelehnt und das Feld benannt. Ein unvollständiger Satz wird bei der Verwendung der Quelle abgelehnt, mit Angabe des fehlenden Werts. Jedes Geheimnis kann eine `${secret:…}`- oder `${env:…}`-Referenz sein. Ein als Literal eingegebenes Geheimnis wird im Tresor der Organisation abgelegt, und die Quelle behält ihre Referenz.

| Quellfeld | Connector-Eigenschaft | Hinweise |
| --- | --- | --- |
| `base_url` oder `host` | `login-url` | Die „Meine Domäne“-URL der Organisation (Setup, dann Meine Domäne). `login.salesforce.com` funktioniert für den Client-Credentials-Flow nicht |
| `username` | `client-id` | Verbraucherschlüssel der verbundenen Anwendung |
| `password` | `client-secret` | Verbrauchergeheimnis der verbundenen Anwendung |
| `mapping.auth_type` | — | `CLIENT_CREDENTIALS` (Standard), `USERNAME_PASSWORD` oder `ACCESS_TOKEN` |
| `mapping.sf_username`, `mapping.sf_password` | `username`, `password` | Nur `USERNAME_PASSWORD`, zusätzlich zu Verbraucherschlüssel und -geheimnis |
| `mapping.security_token` | `security-token` | Nur `USERNAME_PASSWORD`; optional |
| `mapping.access_token`, `mapping.instance_url` | `access-token`, `instance-url` | Nur `ACCESS_TOKEN`; kein Verbraucherschlüssel oder -geheimnis |
| `mapping.api_version` | `api-version` | Optional, zum Beispiel `v61.0` |

Für `CLIENT_CREDENTIALS` braucht die verbundene Anwendung *Enable Client Credentials Flow* und einen *Run As*-Benutzer; jeder Lese- und Schreibvorgang läuft mit den Berechtigungen dieses Benutzers. Seit Summer '23 angelegte Organisationen sperren den Benutzername-Passwort-Flow standardmäßig.

**Lesen.** Auf Trino wird die Quelle über den `salesforce`-Katalog gelesen, der nur liest. Auf jeder anderen Engine bindet die Engine den pgwire-Server der Quelle ein und liest sie an Ort und Stelle.

**Schreiben.** `INSERT`, `UPDATE` und `DELETE` auf einem registrierten sObject sind Mutationen: gesteuert, auditiert und je Umgebung behandelt wie jede andere Mutation. Auf jeder Engine, auch Trino, läuft ein Schreibvorgang auf dem pgwire-Server der Quelle; auf Trino läuft dieser Server nur für Schreibvorgänge. Jede Anweisung wird an Salesforce gesendet und bei der Ausführung festgeschrieben, kann also nicht zurückgerollt werden. Der Server gibt die geschriebenen Zeilen nicht zurück: Eine Anweisung mit `RETURNING`-Klausel wird abgelehnt, und GraphQL bietet für diese Tabellen keine Mutationsfelder an; SQL-`INSERT`, -`UPDATE`, -`DELETE` und -`COPY` sind die Schreibpfade. Ein Schreibvorgang ist eine einzelne Anweisung auf einer Tabelle: `INSERT … ON CONFLICT`, `UPDATE … FROM`, `DELETE … USING`, `MERGE` und `TRUNCATE` werden abgelehnt und das jeweilige Formular benannt. Eine SharePoint-Quelle wird auf dieselbe Weise geschrieben. [tool-verified: `provisa/executor/writable.py` `PGWIRE_SERVER_WRITTEN`; `provisa/api/data/pgwire_write.py`]

**Start.** Bevor er Verbindungen annimmt, liest der Server der Quelle die Spalten jedes sObjects, etwa vier Minuten bei einer Organisation mit 1.200 davon. Das fällt einmal an: Die Describe-Ergebnisse liegen im eigenen Zustandsverzeichnis der Quelle unter dem Datenverzeichnis der Instanz. Der Server wird gestartet, wenn die Quelle registriert oder geladen wird. Auf Trino hält der `salesforce`-Katalog seine eigenen Describe-Ergebnisse, ein Verzeichnis pro Quelle unter `/data/trino/cache/salesforce-describe` im Coordinator, sodass der Aufwand auch dort nur einmal anfällt, wenn dieser Pfad ein Volume ist, das den Container überdauert: das Volume `trino_cache` des Compose-Stacks oder das Coordinator-Cache-Volume des Helm-Charts (`trino.coordinator.cache.persistence`). Bis er Verbindungen annimmt, zeigt „Tabelle registrieren“ den Connector als startend an, und ein Schreibvorgang erhält dieselbe Meldung, statt zu warten. [tool-verified: `provisa/federation/pgwire_replica.py` `build_model_json`, `start_endpoint`]

```yaml
- id: sales-salesforce
  type: salesforce
  base_url: https://acme.my.salesforce.com
  username: ${env:SF_CONSUMER_KEY}
  password: ${env:SF_CONSUMER_SECRET}
  mapping:
    api_version: v61.0
```

Benutzername-Passwort-Flow:

```yaml
- id: sales-salesforce
  type: salesforce
  base_url: https://acme.my.salesforce.com
  username: ${env:SF_CONSUMER_KEY}
  password: ${env:SF_CONSUMER_SECRET}
  mapping:
    auth_type: USERNAME_PASSWORD
    sf_username: ops@acme.com
    sf_password: ${env:SF_PASSWORD}
    security_token: ${env:SF_SECURITY_TOKEN}
```

#### `servicenow`

Jede Tabelle der Instanz steht zur Registrierung bereit; nichts wird automatisch registriert (REQ-1954). Auf einer vollen Instanz können es Tausende Tabellen sein; Register Table gruppiert sie daher nach Thema — jedes Thema ist der Anzeigename eines ServiceNow-Pakets oder „(kein Paket)", wenn eine Tabelle keinem Paket angehört. Jede Tabelle wird als `name — label` angezeigt. Die Auswahl einer Tabelle liest deren Spalten aus der Instanz; das bloße Auflisten liest keine. [tool-verified: `provisa/federation/pgwire_replica.py` `servicenow_table_list`, `servicenow_columns`; `provisa/federation/servicenow.py` `TABLE_LIST`, `COLUMN_LIST`]

Eine ServiceNow-Quelle nennt die vollständige `https://…`-URL der Instanz sowie Benutzername und Passwort. Die URL stammt aus `base_url` oder `host`; ein blosser Host oder ein anderes Schema wird abgelehnt und das Feld benannt (`instanceUrl`). Ein fehlender Benutzername oder ein fehlendes Passwort wird abgelehnt und das jeweilige Feld benannt. Jeder Wert kann eine `${secret:…}`- oder `${env:…}`-Referenz sein. Ein als Literal eingegebenes Geheimnis wird im Tresor der Organisation abgelegt, und die Quelle behält ihre Referenz.

| Quellfeld | Adapter-Eigenschaft | Hinweis |
| --- | --- | --- |
| `base_url` oder `host` | `instanceUrl` | Vollständige `https://…`-URL der Instanz (z. B. `https://acme.service-now.com`). Ein blosser Host oder ein anderes Schema wird abgelehnt |
| `username` | `username` | Basic-Auth-Benutzername |
| `password` | `password` | Basic-Auth-Passwort |

[tool-verified: `provisa/federation/servicenow.py` `servicenow_instance_url`, `servicenow_settings`]

**Lesen.** Auf Trino wird die Quelle über den `servicenow`-Katalog gelesen, der nur liest. Auf jeder anderen Engine bindet die Engine den pgwire-Server der Quelle ein und liest sie an Ort und Stelle. Nur die ausgewählten Spalten werden von der Instanz angefordert (`sysparm_fields`). Ein Filter wird nur in einer Form an die Instanz gesendet (`sysparm_query`), die der Adapter an einer Live-Instanz verifiziert hat; jeder andere Filter sowie jede Sortierung und jedes Limit werden auf die gelesenen Zeilen angewendet. [inferred: the adapter's requirements ledger (kenstott/calcite `docs/requirements/servicenow.yaml`, SNOW-022, SNOW-023, SNOW-030)]

Ein Referenzfeld erscheint als zwei Spalten: `<Feld>` enthält die sys_id des referenzierten Eintrags, und `<Feld>__display` enthält den Anzeigewert. Ein leerer Feldwert ist NULL. Ein Feld, dessen Typ der Adapter nicht abbilden kann, erzeugt einen Fehler, der Tabelle, Feld und Typ benennt. [inferred from adapter behavior; in dieser Sitzung nicht direkt im Provisa-Quellcode überprüft]

Die Tabellensuche (natürliche Sprache) stimmt auf Name, Label und Thema jeder Tabelle ab. Sobald eine Tabelle registriert ist, nehmen ihre Spalten an der Suche teil. [tool-verified: `provisa/discovery/catalog_cache.py` `COLUMNS_PER_TABLE_KINDS` Docstring]

**Server-Lebenszyklus.** Der Server bedient nur die aus ihm registrierten Tabellen. Das Registrieren oder Entfernen einer Tabelle startet den Server neu und provisioniert die Quelle erneut auf der Engine; eine Anweisung, die während dieses Neustarts eintrifft, schlägt fehl. [tool-verified: `provisa/federation/pgwire_replica.py` `SERVES_REGISTERED_TABLES`; `provisa/api/app_rebuild.py` `serve_registered_tables`]

**Schreiben.** `INSERT`, `UPDATE` und `DELETE` auf einer registrierten Tabelle sind Mutationen: gesteuert, auditiert und je Umgebung behandelt wie jede andere Mutation. Auf jeder Engine, auch Trino, läuft ein Schreibvorgang auf dem pgwire-Server der Quelle. Der Server gibt die Zeile zurück, die die Instanz nach dem Schreibvorgang enthält; eine `RETURNING`-Klausel wird daher akzeptiert, und GraphQL bietet Mutationsfelder für diese Tabellen an. Ein Schreibvorgang ist eine einzelne Anweisung auf einer Tabelle: `INSERT … ON CONFLICT`, `UPDATE … FROM`, `DELETE … USING`, `MERGE` und `TRUNCATE` werden abgelehnt und das jeweilige Formular benannt. [tool-verified: `provisa/executor/writable.py` `PGWIRE_SERVER_WRITTEN`, `PGWIRE_SERVER_RETURNS_ROWS`]

**Import-Sets.** Wenn eine Tabelle über eine aktive Transform-Map verfügt, bietet Register Table deren Import-Sets an, und der Steward kann die Tabelle an eines davon binden (eine Tabelle mit mehreren Maps benennt jedes einzeln). Einfügungen in eine gebundene Tabelle laufen über die Import-Set-API der Instanz und die Transformation der jeweiligen Map; Einfügungen in eine ungebundene Tabelle sowie alle Updates und Deletes werden direkt in die Tabelle geschrieben. Eine Zeile, die die Transformation ablehnt, wird zurückgewiesen und die betreffende Zeile benannt; bereits geschriebene Zeilen bleiben erhalten. Die Bindung wird beim Speichern der Tabelle geprüft: Sie muss das Import-Set einer aktiven Transform-Map in die Tabelle sein, auf einer ServiceNow-Quelle. [tool-verified: `provisa/api/admin/_import_set.py` `table_import_set_refusal`; `provisa/federation/servicenow.py` `servicenow_settings`; `provisa/federation/pgwire_replica.py` `servicenow_transform_maps`]

```yaml
- id: helpdesk-sn
  type: servicenow
  base_url: https://acme.service-now.com
  username: ${env:SN_USERNAME}
  password: ${env:SN_PASSWORD}
```

#### `cloudops`

Das Cloud-Inventar stellt die Ressourcen von Azure, AWS und GCP als einen Satz Tabellen dar: `compute_resources`, `storage_resources`, `kubernetes_clusters`, `database_resources`, `network_resources`, `iam_resources`, `container_registries` und `compute_security_groups`, das eine Compute-Ressource mit ihren Sicherheitsgruppen verknüpft. Jede Tabelle hat über die drei Clouds hinweg dieselben Spalten, und ihre Spalte `cloud_provider` nennt die Cloud, aus der eine Zeile stammt. Die Quelle liest nur, und ihre Tabellen werden wie alle anderen von einem Steward registriert (REQ-1947). [tool-verified: `provisa/federation/cloudops.py` `cloudops_settings`; `provisa/federation/trino_connectors.py` `TrinoCloudopsConnector`]

Eine Quelle nennt eine oder mehrere Clouds. Für jede Cloud gilt alles oder nichts: Eine Cloud mit nur einem Teil ihrer erforderlichen Werte wird abgelehnt, mit Angabe der fehlenden Werte, ebenso eine Quelle, die keine Cloud nennt. Die Quelle liest genau die Clouds, die sie nennt. Alle Werte stehen in `mapping`, und jedes Geheimnis kann eine `${secret:…}`- oder `${env:…}`-Referenz sein. Ein als Literal eingegebenes Geheimnis wird im Tresor der Organisation abgelegt, und die Quelle behält ihre Referenz.

| Cloud | `mapping`-Schlüssel | Connector-Eigenschaft | Hinweise |
| --- | --- | --- | --- |
| Azure | `azure_tenant_id` | `azure.tenant-id` | Erforderlich |
| Azure | `azure_client_id` | `azure.client-id` | Erforderlich; die Client-ID der App-Registrierung |
| Azure | `azure_client_secret` | `azure.client-secret` | Erforderlich; Geheimnis |
| Azure | `azure_subscription_ids` | `azure.subscription-ids` | Erforderlich; durch Kommas getrennt |
| AWS | `aws_access_key_id` | `aws.access-key-id` | Erforderlich |
| AWS | `aws_secret_access_key` | `aws.secret-access-key` | Erforderlich; Geheimnis |
| AWS | `aws_region` | `aws.region` | Erforderlich, zum Beispiel `us-east-1` |
| AWS | `aws_account_ids` | `aws.account-ids` | Erforderlich; durch Kommas getrennt |
| AWS | `aws_role_arn` | `aws.role-arn` | Optional; eine Rolle, die für kontoübergreifenden Zugriff übernommen wird |
| GCP | `gcp_credentials_path` | `gcp.credentials-path` | Erforderlich; ABSOLUTER Pfad zu einer JSON-Schlüsseldatei eines Dienstkontos |
| GCP | `gcp_project_ids` | `gcp.project-ids` | Erforderlich; durch Kommas getrennt |
| — | `cache_ttl_minutes` | `cache.ttl-minutes` | Optional; wie lange ein Ergebnis wiederverwendet wird, bevor die Clouds erneut gefragt werden (Adapter-Standard 5) |

Die GCP-Schlüsseldatei wird von dem geöffnet, was die Quelle liest. Auf Trino ist das der Trino-Server, der Pfad muss dort also existieren. Auf jeder anderen Engine ist es der pgwire-Server der Quelle auf dem Provisa-Host, dessen Arbeitsverzeichnis sein eigenes Zustandsverzeichnis ist, sodass ein relativer Pfad abgelehnt wird.

Auf Trino wird die Quelle über den `cloudops`-Katalog gelesen. Auf jeder anderen Engine bindet die Engine den pgwire-Server der Quelle ein und liest sie an Ort und Stelle, wie eine SharePoint-Quelle.

```yaml
- id: cloud-estate
  type: cloudops
  mapping:
    aws_access_key_id: ${env:CLOUDOPS_AWS_ACCESS_KEY_ID}
    aws_secret_access_key: ${env:CLOUDOPS_AWS_SECRET_ACCESS_KEY}
    aws_region: us-east-1
    aws_account_ids: "111111111111,222222222222"
    azure_tenant_id: ${env:CLOUDOPS_AZURE_TENANT_ID}
    azure_client_id: ${env:CLOUDOPS_AZURE_CLIENT_ID}
    azure_client_secret: ${env:CLOUDOPS_AZURE_CLIENT_SECRET}
    azure_subscription_ids: "sub-1,sub-2"
```

#### `splunk`

Splunk-Suchergebnisse sind als Tabellen abfragbar (z. B. `internal_server`) (REQ-721). Die Connector-URL stammt aus `base_url` oder wird als `https://{host}:{port}` mit Standardport `8089` konstruiert (REQ-722). Auth: Ist `mapping.use_token` `true` (Standard), wird `password` als API-Token übergeben; ist es `false`, werden `username` und `password` als separate Zugangsdaten übergeben (REQ-723). [tool-verified: `provisa/federation/trino_connectors.py` lines 262–286]

| Quellfeld | Connector-Eigenschaft | Hinweise |
| --- | --- | --- |
| `base_url` / `host` + `port` | `url` | `base_url`, sonst `https://host:port` (Standardport 8089) |
| `password` | `token` oder `password` | Token, wenn `use_token: true` |
| `username` | `user` | nur, wenn `use_token: false` |
| `database` | `app` | auf eine Splunk-App einschränken |
| `mapping.datamodel_filter` | `datamodel-filter` | auf ein Data Model filtern |
| `mapping.disable_ssl_validation` | `disable-ssl-validation` | für selbstsignierte Zertifikate (REQ-724) |

Auf dem pgwire-Replica-Pfad (jede Engine außer Trino) werden dieselben vier optionalen Einstellungen zu den Calcite-`model.json`-Operanden-Keys `app`, `token`/`username`+`password`, `datamodelFilter` und `disableSslValidation` — die letzten beiden in den Typen, in die `SplunkSchemaFactory` sie castet, ein String und ein Boolean (REQ-1694). [tool-verified: `provisa/federation/pgwire_replica.py` `_splunk_operand`]

```yaml
- id: ops-splunk
  type: splunk
  host: splunk
  port: 8089
  password: ${env:SPLUNK_TOKEN}
  mapping:
    use_token: true
    disable_ssl_validation: true
```

### API-Quellen

Registrieren Sie jeden HTTP-Endpunkt als abfragbare Tabelle. [tool-verified: `provisa/core/models.py` `SourceType` enum] (REQ-314, REQ-307, REQ-322)

| API-Typ | Discovery | Spaltenableitung |
| --------- | ----------- | ----------------- |
| `openapi` | OpenAPI-Spec-Parsing (REQ-314, REQ-316) | Primitive → nativ, Objekte → JSONB |
| `graphql_remote` | Schema-Introspektion (REQ-307, REQ-308) | Primitive → nativ, Objekte → JSONB |
| `grpc_remote` | Server Reflection (REQ-322, REQ-325) | Primitive → nativ, Objekte → JSONB |

API-Antworten werden abgerufen, in PostgreSQL gecacht (konfigurierbare TTL) und als GraphQL-Typen offengelegt (REQ-309, REQ-318, REQ-327). Gecachte Tabellen nehmen wie jede andere Quelle an föderierten Abfragen teil (REQ-313).

**JSONB-Regeln**: Komplexe Spalten (Objekte, Arrays), die als JSONB gespeichert werden, sind nicht filterbar (REQ-119). Der Zugriff auf Unterfelder verwendet die `->>`-Extraktion in SQL (REQ-151). Beziehungen werden zwischen Tabellen über skalare FK-Spalten deklariert — JSONB-Blob-Spalten sind keine Join-Ziele. Verwenden Sie JSONB-Promotion, um verschachtelte Felder in native skalare Spalten umzuwandeln, wenn Filtern oder Joinen darauf benötigt wird (REQ-119).

#### GitHub und GitLab

GitHub und GitLab sind Marken-Quellen, die `graphql_remote` trägt: Jede erscheint im Sources-Formular unter ihrem eigenen Namen und registriert sich als Remote-GraphQL-Quelle, die ihre Marke festhält. Das Formular verlangt ein Personal Access Token und sonst nichts. Der Endpunkt (`https://api.github.com/graphql`, `https://gitlab.com/api/graphql`) und das Schema werden mit Provisa ausgeliefert, daher wird das Schema bei der Registrierung nicht introspiziert. Das Token wird beim Hinzufügen der Quelle geprüft. Das Hinzufügen der Quelle registriert keine Tabellen: Jede Tabelle, die das Schema anbietet, steht unter dem Namensraum der Quelle (`gh`, `gl`) bereit, und der Steward registriert die gewünschten. Ein Feld, das das Token nicht lesen darf, wird beim Registrieren aus einer Tabelle ausgelassen. [tool-verified: `provisa/graphql_remote/brands.py` `BRANDS`] (REQ-1923)

#### Ausschlüsse bei einer aus einer Spezifikation gebauten Quelle

Eine veröffentlichte OpenAPI-Spezifikation beschreibt alles, was die entfernte API annimmt, auch das, was ihr Hersteller als veraltet markiert hat und was ein Deployment nie senden darf. Eine OpenAPI-Quelle kann Ausschlüsse tragen: Dinge in der Spezifikation, die die Quelle nicht anbietet. (REQ-1957)

| Ausgeschlossen | Benannt durch | Wirkung |
|---|---|---|
| Eine Operation | `method` und `path` | Wird nicht zur Registrierung als Tabelle oder als Befehl aufgelistet |
| Ein Anfrageargument | `name`, bei einer Operation (`method` und `path`) oder, wenn keines von beiden, bei jeder Operation, die es hat | Gehört nicht zu den Argumenten der Operation, wird nicht angezeigt, nie gesendet |

Ausschlüsse werden unter `exclusions` im `mapping` der Quelle gesetzt:

```yaml
sources:
  - id: shop-api
    type: openapi
    path: https://shop.example.com/openapi.json
    mapping:
      exclusions:
        operations:
          - {method: POST, path: /v1/tokens}
        arguments:
          - {name: source, method: POST, path: /v1/customers}
          - {name: legacy_token}          # on every operation that has it
```

Sie werden beim Laden auf die Spezifikation angewendet, sodass die Registrierungsliste, die erzeugten Befehle und die gesendete Anfrage alle eine Spezifikation sehen, in der die ausgeschlossenen Dinge nicht existieren. Eine Body-Eigenschaft sowie ein Query-, Header- oder Cookie-Parameter können ausgeschlossen werden; ein Pfadparameter nicht, weil er Teil der Adresse der Operation ist.

Ein Ausschluss, der eine Operation oder ein Argument benennt, das die Spezifikation nicht hat, lässt das Laden der Spezifikation dieser Quelle fehlschlagen und benennt jeden veralteten Eintrag, sodass eine Liste auffällt, die zu einer neueren Spezifikation nicht mehr passt.

Eine Marken-Quelle liefert ihre eigenen Ausschlüsse als Teil ihrer Kuratierung mit, und die eines Operators werden ihnen hinzugefügt. Die Stripe-Quelle schließt die veraltete Token-und-Source-Zahlungsintegration von Stripe aus: das Erstellen einer Charge, die Tokens- und Sources-APIs, das Hinzufügen einer Karte oder eines Bankkontos zu einem Kunden aus einem Token sowie die Argumente `source`, `card`, `bank_account` und `default_card` von Schreibvorgängen für Kunden und Rechnungszahlungen. Zahlungen werden über Payment Intents, Payment Methods und Setup Intents abgewickelt, die die Quelle anbietet. Das Lesen und Löschen von Zahlungsquellen, die ein Konto bereits hat, bleibt im Angebot.


### GovData

Offene Daten der US-Regierung. Der Zugriff ist nach Themengruppierung partitioniert. [tool-verified: `provisa/core/models.py` lines 543–609]

Einer Quelle werden ein oder mehrere Themen zugewiesen, und jedes Thema bringt die unten aufgeführten Adapter-Schemas mit. Ein Schema kann zu mehr als einem Thema gehören (`census`). Die Schemas `ref` und `geo` sind Linker-Schemas: Referenzdaten und Geografie, über die die Tabellen jedes Themas joinen, sodass jede Quelle sie bereitstellt, welche Themen sie auch erhält. Die Liste ist einmal auf dem Server festgelegt und wird per Test an die Schemas gebunden, die das gepinnte Adapter-Bundle bereitstellt. [tool-verified: `provisa/core/models.py` `GOVDATA_SUBJECT_SCHEMAS`, `GOVDATA_LINKER_SCHEMAS`; `tests/unit/test_govdata_subject_schemas.py`]

| Thema | Offengelegte Schemas |
| --------- | ----------------- |
| `COMMERCE` | `sec`, `patents`, `cftc` |
| `ECONOMY` | `econ`, `econ_reference`, `ag`, `banking`, `fiscal`, `housing`, `transport` |
| `EDUCATION` | `census`, `edu`, `research` |
| `HEALTH` | `health` |
| `CYBER` | `cyber_threat`, `cyber_vuln` |
| `PUBLIC_SAFETY` | `crime`, `disasters` |
| `ENVIRONMENT` | `lands`, `environment` |
| `WEATHER` | `weather` |
| `ENERGY` | `energy` |
| `GOVERNMENT` | `fedregister`, `fec`, `officials`, `law` |
| `DEMOGRAPHICS` | `census` |
| jede Quelle | `ref`, `geo` |

`ALL` ist die Kurzform eines Abonnements für jedes Thema; es ist keine Auswahl im Sources-Formular.


```yaml
sources:

  - id: federal-commerce
    type: govdata
    subject: COMMERCE
    domain_id: federal-analytics
    description: U.S. commerce and securities data
```

| Feld | Erforderlich | Standard | Beschreibung |
| ------- | ---------- | --------- | ------------- |
| `id` | Ja | — | Eindeutiger Bezeichner |
| `subject` | Ja | — | Einer der obigen Themenwerte |
| `domain_id` | Ja | — | Domäne, zu der diese Quelle gehört |
| `description` | Nein | `""` | Menschenlesbare Beschreibung |

Eine im Admin angelegte AskAmerica-Quelle nimmt eine Anmeldeinformation entgegen, den API-Schlüssel. Provisa legt der API von AskAmerica den Schlüssel vor und erhält die kurzlebigen, schreibgeschützten Speicher-Anmeldeinformationen, mit denen die Daten gelesen werden; der Schlüssel wird dort namentlich abgelehnt, wenn er unbekannt oder widerrufen ist. [tool-verified: `provisa/federation/askamerica.py`]

Die Quelle ist dann eine Postgres-Wire-Quelle wie die SharePoint-, Salesforce- und Cloud-Inventar-Quellen: Provisa startet dafür den mitgelieferten `pgwire-govdata`-Server, mit dem Schlüssel und diesen Anmeldeinformationen in der Umgebung des Servers, und jede Engine erreicht diesen Server so, wie sie den eines Geschwisters erreicht. DuckDB, Postgres und ClickHouse binden ihn ein und lesen seine Tabellen an Ort und Stelle, sodass eine AskAmerica-Tabelle mit Tabellen anderer Quellen joint, unter Sichten liegt und wie jede andere ausgeliefert wird. Trino hat dafür keinen Connector und liest ein Replikat, das über den Server gelandet wurde: eine Kopie der Tabelle im Materialisierungs-Store, so frisch wie ihr letzter Refresh unter den Cache- und Replikationseinstellungen der Tabelle und nicht zur Abfragezeit gelesen. Eine Tabelle wird aus dem Adapter-Schema gelesen, das sie nennt (`sec`, `econ` und so weiter). [tool-verified: `provisa/federation/pgwire_replica.py`, `provisa/federation/connector_duckdb.py`, `provisa/federation/clickhouse_connectors.py`]

Der Server bindet seine Schemas aus dem Objektspeicher ein, bevor er eine Verbindung annimmt; das dauert beim ersten Start Minuten. Er wird gestartet, wenn die Quelle gespeichert wird; bis er bereit ist, meldet das Register-Table-Formular, dass die Quelle noch startet. [tool-verified: `provisa/federation/pgwire_replica.py` `start_when_saved`]

### Wo das Passwort einer Quelle lebt

Das Passwort einer Quelle wird nie neben den übrigen Verbindungseinstellungen gespeichert. Die
`sources`-Zeile der Control Plane trägt eine `password_ref`-Spalte mit dem, was für das Passwort
eingegeben wurde: dem Wert selbst oder einer Referenz wie `${env:PG_PASSWORD}` oder
`${secret:SNOWFLAKE_KEY}`. Sie wird in dem Moment aufgelöst, in dem die Quelle angewählt wird,
innerhalb der Organisation, in deren Namen die Anfrage läuft. [tool-verified:
`provisa/core/schema_org.py`, `provisa/core/repositories/source.py`]

Ein Wert ohne `${…}` wird unverändert verwendet. `${env:VAR}` liest die Prozessumgebung des
Deployments und benötigt keine Bindung. `${secret:NAME}` benennt ein Secret, das einer Organisation
gehört, sodass es nur innerhalb der eigenen Operationen dieser Organisation aufgelöst wird: die
Admin-Introspektions-Nahtstellen und das Query-Terminal, das jede Oberfläche erreicht, stellen diese
Bindung her. [tool-verified: `provisa/core/secrets.py` `resolve_secrets`; `provisa/pgwire/_pipeline.py`
`_execute_plan`]

Das Feld hält, was Sie hineinschreiben, gleichgültig wie die Quelle registriert wurde:

- **Aus der Konfiguration.** Die Datei ist der Datensatz: Provisa kopiert den Wert oder die Referenz
  wortwörtlich in `password_ref`.
- **Aus dem Sources-Formular.** Was in das Passwortfeld eingegeben wird, wird wortwörtlich
  gespeichert, ein Wert wie eine Referenz. Provisa schreibt dafür nichts in den Vault der
  Organisation und erfindet keinen Secret-Namen. Um eine Anmeldeinformation aus der Zeile der
  Control Plane herauszuhalten, legen Sie das Secret selbst an (siehe [Secrets](secrets.md)) und
  tippen `${secret:NAME}` in das Feld. [tool-verified: `provisa/api/admin/schema_mutation.py`
  `create_source`]

Ein als Wert eingegebener Wert wird so, wie eingegeben, in der Datenbank der Control Plane
gespeichert. Das erneute Eintippen des Passworts ersetzt den Text des Felds. Das Löschen der Quelle
entfernt ihre Zeile und nichts aus dem Vault: Ein Secret, das Sie angelegt haben, gehört Ihnen.
[tool-verified: `provisa/api/admin/schema_mutation.py` `delete_source`;
`tests/unit/test_no_product_written_secrets.py`]


`password_ref` wandert nicht zwischen Umgebungen (REQ-1491). Ein Branch oder eine kopierte Umgebung
liefert ihre eigenen Verbindungswerte, und der Vault, den eine Referenz benennt, gehört zu welcher
Umgebung auch immer sie geliefert hat. [tool-verified: `provisa/core/env_classes.py` `BINDING_COLUMNS`]

### Data-Profiler {: #data-profiler }

Ein Data Profiler ist eine Quelle, die einen Namen, einen Zeitplan und Lauf-Standardwerte hält, sonst nichts. Sie wird nie introspiziert. Tabellen anderer Quellen werden ihr hinzugefügt, und jeder Lauf misst sie und schreibt seine Zeilen in die Control Plane der Organisation, wo sie wie die Tabellen jeder anderen Quelle gelesen werden. Wie Sie einen Profiler anlegen und Tabellen hinzufügen, steht unter [Testdaten](test-data.md). [tool-verified: `provisa/core/models.py` `SourceType.data_profiler`; `provisa/federation/strategy.py` `_MATERIALIZE_ONLY`] (REQ-1934)

### Data-Quality-Checker (REQ-1443) {: #data-quality-checkers-req-1443 }

Ein Data-Quality-Checker ist ein Quelltyp, kein Subsystem. Seine Scan-Ausgabe sind Daten: Ein Check-Ergebnis ist eine Beobachtung, sodass es über den gewöhnlichen Quellpfad landet und Kadenz, Freshness, Events, Lineage, Governance, RLS, Grid und Export von jeder anderen Quelle erbt. [tool-verified: `provisa/core/models.py` lines 110–116 `SourceType.soda`, `SourceType.great_expectations`; `provisa/events/source_loader.py` `make_dq_loader`]

Zwei werden unterstützt, und die Wahl ist ebenso eine Lizenzfrage wie eine Feature-Frage.

| Quelltyp | Vertrags-Dialekt | Extra | Lizenz | Gehostete Cloud-Plane |
| ------------ | ----------------- | ------- | --------- | -------------------- |
| `soda` | Soda-Contract-YAML | `pip install .[soda]` (`soda-postgres`) | Elastic License 2.0 | Abgelehnt — siehe unten |
| `great_expectations` | Expectation-Suite-JSON | `pip install .[gx]` (`great-expectations[postgresql]`) | Apache 2.0 | Erlaubt |

Die Elastic License 2.0 verbietet, die Software Dritten als gehosteten oder verwalteten Dienst bereitzustellen, und Soda innerhalb der SaaS-Plane im Namen eines Mandanten laufen zu lassen ist genau das. `config/capabilities.yaml` trägt die Aufteilung als `cloud_eligible: false` auf der `soda`-Option, und die gehostete Plane liest dieses Flag. Ein gehostetes Deployment, das Soda möchte, erreicht einen vom Betreiber bereitgestellten Soda-Endpunkt, den der Betreiber selbst betreibt. [tool-verified: `config/capabilities.yaml` lines 197–203]

Provisa bündelt und verlinkt nichts. Der Scan läuft in einem Kind-Interpreter (`python -m provisa.dq.worker`), dem einzigen Ort, an dem `soda_core` oder `great_expectations` importiert wird, sodass ein source-available Checker den Serverprozess nie erreicht und ein Checker-Absturz einen Subprozess tötet statt die Event-Loop. [tool-verified: `provisa/dq/runner.py` `build_command`, `run_contract`]

**Die Quelle zeigt auf Provisas eigenen pgwire-Endpunkt.** Das ist, was es einem Postgres-Treiber erlaubt, eine Snowflake- oder Iceberg-gestützte Tabelle zu prüfen: Der Checker scannt die föderierte Sicht, nicht das darunterliegende System. Weil Richtlinie auf diese Verbindung angewendet wird, wird die Scan-Identität deklariert statt geerbt — eine gefilterte Zeilenmenge darf nie einen stillschweigend bestehenden Check erzeugen.

```yaml
sources:

  - id: dq
    type: soda
    domain_id: sales-analytics
    description: Soda contract scans over the governed estate
    mapping:
      host: localhost
      port: 5439          # Provisa's pgwire endpoint
      database: provisa
      user: dq_scanner    # the scan identity, declared explicitly
      password: ${env:PROVISA_DQ_PASSWORD}
```

**Eine Ergebnistabelle pro Vertrag, und der Vertrag ist die gesamte Registrierung.** Die Tabelle trägt `dq_contract` — den Vertragstext wortwörtlich — und sonst nichts über ihre Form. Spalten, Watermark und Promotions werden alle abgeleitet. [tool-verified: `provisa/dq/registration.py` `derive_checker_table`]

```yaml
tables:

  - source_id: dq
    schema_name: quality
    table_name: orders_scan
    domain_id: sales-analytics
    change_signal: ttl_probe
    cache_ttl: 3600
    columns:
      - name: scan_id          # declared only to carry visible_to; replaced at parse
        visible_to: [analyst, admin]
    dq_contract: |
      dataset: provisa/sales/orders
      columns:
        - name: customer_id
          checks:
            - missing:
                threshold:
                  metric: percent
                  must_be_less_than: 1
      checks:
        - row_count:
            must_be_greater_than: 0
```

Was die Registrierung aus diesem Text ableitet:

- **Lineage.** Der Vertrag benennt bereits sein Zieldataset, sodass die Registrierung ihn so parst, wie `extract_inputs` SQL parst (REQ-939), und ihn auf die geregelte Tabelle auflöst. Eine Definition, keine zweite Kopie, die driften kann. Ein Vertrag, der ein ungeregeltes Dataset benennt, schlägt bei der Registrierung laut fehl, statt Zeilen zu landen, die niemand angefordert hat.
- **Spalten.** Der Ergebnis-Umschlag gehört dem Checker, nicht dem Betreiber — 16 mitgelieferte Spalten von `scan_id` bis `diagnostics`. Deklarierte Spalten werden nur für ihr `visible_to` gelesen, das einstimmig sein muss, und dann ersetzt. [tool-verified: `provisa/dq/results.py` `_ENVELOPE`, `results_columns`]
- **Watermark.** `scan_time` wird zum Watermark, was das Landen zu einem Append macht (REQ-982). Scan-Historie akkumuliert ohne Historien-Subsystem.
- **Promotions.** `freshness_max_timestamp` und `dataset_rows_tested` werden aus dem `diagnostics`-jsonb als typisierte Spalten hochgestuft (REQ-119). Fügen Sie weitere hinzu, wie Sie es bei jeder anderen jsonb-Spalte täten. [tool-verified: `provisa/dq/results.py` `DQ_PROMOTIONS`]

Timing führt keine neuen Felder ein. `change_signal` plus `cache_ttl` geben die Poll-Kadenz vor; `mv_debounce_quiet` und `mv_debounce_max_delay` fassen einen vorgelagerten Burst zu einem Scan zusammen (REQ-963); eine Kalendergranularität macht ihn periodisch (REQ-962); `expected_events` hält den Scan zurück, bis seine Eingaben durch das Fenster frisch sind (REQ-961). Die Poll-Schleife ist der Scan-Scheduler.

`outcome` ist eines von `pass`, `fail`, `warn`, `error`, `skipped`. Keines davon ist ein Urteil — Durchsetzung, falls gewünscht, ist eine separate, spätere Deklaration: ein Preflight oder eine materialisierte Sicht über den gelandeten Ergebnissen. Weil eine gelandete Beobachtung keine Determinismus-Verpflichtung trägt (REQ-964), sind hier nichtdeterministische Checks zulässig, die auf einem Preflight-Gate nie sitzen könnten — Anomalie-Score, Trailing-Window-Änderung, Freshness gegen jetzt.

Der Vertrag wird in der UI verfasst, im Data-Quality-Panel der Tabellen-Bearbeitungsoberfläche, und der rohe Vertragstext dort ist immer die Source of Truth. Ein Trockenlauf führt den Vertrag gegen die Live-Tabelle aus und zeigt die Ergebnisse, ohne sie zu landen — so erwischen Sie einen Vertrag, dessen Datasetname an eine unerwartete Stelle aufgelöst wurde und der sonst nichts als bestehende Zeilen landen würde.

---

## Benutzerdefinierte Connectors (REQ-1177)

Die nativen Federation-Engines — Postgres, DuckDB und ClickHouse — gewinnen Erreichbarkeit zu einem neuen Quelltyp, wenn ein Betreiber dafür einen Connector in `config/custom_connectors.yaml` deklariert. Kein Code erforderlich. [tool-verified: `provisa/federation/custom_connectors.py` `load_custom_connectors`; `provisa/federation/engine.py` `build_pg_engine`, `build_duckdb_engine`, `build_clickhouse_engine`]

Connector-Erweiterbarkeit selbst geht dem voraus. Die Trino-Engine ist auf ihrer eigenen Schicht seit Langem erweiterbar — ein generischer JDBC-Connector, parametrisiert pro Quelltyp, ein Katalog-`.properties`-Body pro Typ, und Provisas eigene benutzerdefinierte Trino-Connector-Plugins (Splunk, SharePoint, Calcite). [tool-verified: `provisa/federation/trino_connectors.py` `_TrinoJdbcConnector`, `_TRINO_JDBC_TYPES`; `trino/plugins/trino-splunk`, `trino/plugins/trino-sharepoint`, `trino/plugins/trino-calcite`] REQ-1177 bringt dieselbe konfigurationsgesteuerte Erweiterbarkeit zu den zwei nativen, clusterlosen Engines, die zuvor eine feste Connector-Menge trugen.

Die Konfiguration wird leer ausgeliefert. Eingebaute Connectors decken die Reichweite von Haus aus ab; alles in dieser Datei ist vom Betreiber verfasst. [tool-verified: `config/custom_connectors.yaml` line 52: `connectors: []`] Setzen Sie `PROVISA_CUSTOM_CONNECTORS`, um auf einen anderen Pfad zu verweisen (nützlich für Tests).

### Deskriptor-Arten

| Engine | Art | Mechanismus | Was der Deskriptor liefert |
| --- | --- | --- | --- |
| `postgres` | `pg_fdw` | SQL/MED (ISO-Standard) | `extension`, `server_options`, `user_mapping`, `supports_import`, `table_options`, `remote_schema` |
| `duckdb` | `duckdb_attach` | INSTALL/LOAD + ATTACH | `extension`, `probe_symbol`, `attach_template`, `remote_schema` |
| `duckdb` | `duckdb_scan` | INSTALL/LOAD + Scanner-View | `extension`, `probe_symbol`, `scan_template` |
| `clickhouse` | `clickhouse_database` | `CREATE DATABASE ENGINE=…` (legt automatisch jede entfernte Tabelle offen) | `ch_engine`, `engine_template` |
| `clickhouse` | `clickhouse_table` | `CREATE TABLE ENGINE=…` pro Tabelle (Spalten aus der Registry) | `ch_engine`, `engine_template` (kann `{table}` tragen) |
| `clickhouse` | `clickhouse_scan` | `CREATE TABLE ENGINE=…`, ClickHouse leitet das Schema ab | `ch_engine`, `engine_template` |

**Postgres ist generisch.** SQL/MED ist ein ISO-Standard, sodass jeder konforme FDW dieselbe DDL-Form teilt: `CREATE SERVER … FOREIGN DATA WRAPPER <fdw> OPTIONS(…)`, optional `CREATE USER MAPPING`, dann entweder `IMPORT FOREIGN SCHEMA` (wenn `supports_import: true`) oder ein explizites `CREATE FOREIGN TABLE` pro Tabelle (wenn `false`). Ein `pg_fdw`-Deskriptor liefert nur die Pro-FDW-Varianz — Erweiterungsname, Server-Options-Keys, User-Mapping-Keys, Import-Flag, Tabellen-Optionen. Jeder standardkonforme FDW ist daher allein aus der Konfiguration ansteuerbar. [tool-verified: `provisa/federation/custom_connectors.py` `GenericPgFdwConnector.details` lines 98–125]

**DuckDB unterstützt zwei Mechanismen.** Eine Erweiterung, die einen Katalog über ATTACH offenlegt, verwendet `duckdb_attach`; eine, die eine lesende Table-Function offenlegt, verwendet `duckdb_scan`. Eine Erweiterung, die zu keinem der beiden Muster passt, wird nicht unterstützt. [tool-verified: `provisa/federation/custom_connectors.py` `GenericDuckDbAttachConnector`, `GenericDuckDbScanConnector`]

**ClickHouse unterstützt drei Mechanismen**, einen pro Integrations-Engine-Form: eine relationale DATABASE-Engine, die automatisch jede entfernte Tabelle offenlegt (`clickhouse_database`, z. B. Redis/MySQL), eine Pro-Tabelle-Engine, deren Spalten die Registry liefert (`clickhouse_table`, z. B. die JDBC-/ODBC-Brücke — der `engine_template` kann einen `{table}`-Platzhalter tragen, den die Laufzeit bindet), und eine Datei-/Lake-/URL-Engine, deren Schema ClickHouse ableitet (`clickhouse_scan`, z. B. HDFS/URL). SQLite (DATABASE-Engine, Datei, kein Server) und Hudi (Lakehouse, Zero-Copy) werden OOTB ausgeliefert. [tool-verified: `provisa/federation/custom_connectors.py` `GenericClickHouseDatabaseConnector`, `GenericClickHouseTableConnector`, `GenericClickHouseScanConnector`; `provisa/federation/clickhouse_connectors.py` `ClickHouseSqliteConnector`, `ClickHouseHudiConnector`] (REQ-1178)

Ein unbekannter `kind`-Wert schlägt beim Start laut fehl — ein Deskriptor-Tippfehler darf einen Quelltyp nicht stillschweigend unerreichbar machen. [tool-verified: `provisa/federation/custom_connectors.py` `load_custom_connectors` lines 178–197]

### Probe-Gating

Verfügbarkeit wird zur Attach-Zeit gegen den Standard-Discovery-Katalog jeder Engine geprüft:

- **Postgres** — prüft `pg_extension`, dann `pg_available_extensions`. [tool-verified: `provisa/federation/connector_duckdb.py` `_probe_pg_extension` lines 333–344]
- **DuckDB** — führt `INSTALL`/`LOAD` aus und prüft `duckdb_functions()` auf das deklarierte `probe_symbol`. [tool-verified: `provisa/federation/connector_duckdb.py` `_DuckDBExtensionConnector.probe` lines 160–180]
- **ClickHouse** — prüft `system.table_engines` auf die deklarierte `ch_engine`; fehlt sie im Build, schlägt es laut fehl. [tool-verified: `provisa/federation/custom_connectors.py` `_probe_clickhouse_engine`]

Eine deklarierte Erweiterung, die nicht installierbar ist, schlägt laut fehl. Kein stiller Skip, kein Fallback. Ein Connector, dessen Probe fehlschlägt, ist für dieses Deployment schlicht nicht aktiv.

### Template-Variablen

Jeder `server_options`-Wert, `user_mapping`-Wert, `attach_template` und `scan_template` kann `{field}`-Platzhalter verwenden. Verfügbare Felder: [tool-verified: `provisa/federation/custom_connectors.py` `_source_fields` lines 53–63]

`{id}`, `{host}`, `{port}`, `{database}`, `{username}`, `{password}`, `{path}`, `{schema_name}`, `{table_name}`, plus jeder Key aus `federation_hints`. DuckDB-Attach-Templates erhalten außerdem `{alias}` — den internen Katalog-Alias, den Provisa der angehängten Datenbank zuweist.

Ein Template, das ein unbekanntes Feld referenziert, schlägt zur Attach-Zeit laut fehl und macht eine Deskriptor-/Quell-Fehlpassung sichtbar, bevor defektes DDL die Engine erreicht.

### Beispiele

**Postgres — MongoDB über `mongo_fdw` (kein Schema-Import; Spalten pro Tabelle geliefert)**

```yaml
# config/custom_connectors.yaml
connectors:
  - engine: postgres
    source_type: mongodb
    kind: pg_fdw
    extension: mongo_fdw
    mechanism: attach_r
    server_options:
      address: "{host}"
      port: "{port}"
    user_mapping:
      username: "{username}"
      password: "{password}"
    supports_import: false
    table_options:
      database: "{database}"
      collection: "{table_name}"
```

**DuckDB — Excel-Dateien über `read_xlsx` (Scan-Table-Function)**

```yaml
  - engine: duckdb
    source_type: xlsx
    kind: duckdb_scan
    extension: excel
    install_from_community: false
    probe_symbol: read_xlsx
    scan_template: "read_xlsx('{path}')"
```

[tool-verified: `config/custom_connectors.yaml` commented examples, lines 26–50]

Sobald einer der beiden Deskriptoren vorhanden ist, routet die Registrierung einer Quelle mit dem deklarierten `source_type` über den benutzerdefinierten Connector, vorbehaltlich einer erfolgreichen Probe. Keine weitere Konfigurationsänderung ist nötig.

---

## Warehouses als benannte Quellen {: #warehouses-as-named-sources }

Snowflake, Databricks und ClickHouse können unabhängig davon, welche Federation-Engine aktiv ist, als benannte Quellen registriert werden. [tool-verified: `executor/drivers/snowflake.py` (REQ-988), `executor/drivers/databricks.py` (REQ-987), `executor/drivers/clickhouse.py` (REQ-986)]

Bei Registrierung liest Provisa das Warehouse über den DirectDriver der Quelle und landet ein Replikat im Materialisierungs-Store der aktiven Engine. Die Abfrage läuft dann gegen dieses Replikat. Das unterscheidet sich vom traditionellen direktfähigen Pfad (asyncpg, aiomysql), bei dem die Engine vollständig umgangen wird — hier führt die Engine die Abfrage weiterhin aus, aber gegen ein lokales Replikat statt bei jeder Anfrage über die Leitung zum Warehouse.

Reads sind Arrow-nativ, wo das Warehouse es unterstützt: Databricks verwendet Cloud Fetch, Snowflake verwendet `fetch_arrow_table`, und ClickHouse verwendet die native columnar HTTP-Schnittstelle.

Erweiterte Verbindungsparameter, die die Standardfelder `host`/`port`/`username`/`password` nicht tragen können, gehen in `federation_hints`:

```yaml
sources:
  - id: my-databricks
    type: databricks
    host: my-workspace.azuredatabricks.net
    password: ${env:DATABRICKS_TOKEN}
    federation_hints:
      http_path: /sql/1.0/warehouses/xxxx   # required — the SQL Warehouse connection detail

  - id: my-snowflake
    type: snowflake
    host: org.snowflakecomputing.com
    username: svc_provisa
    password: ${env:SNOWFLAKE_PASSWORD}
    federation_hints:
      account: myorg-myaccount    # required — Snowflake account identifier
      warehouse: COMPUTE_WH       # optional — virtual warehouse to use
      role: PROVISA_ROLE          # optional — Snowflake role

  - id: my-clickhouse
    type: clickhouse
    host: ch.example.com
    port: 8123
    database: analytics
    username: default
    password: ${env:CLICKHOUSE_PASSWORD}
    federation_hints:
      secure: "true"              # optional — enables TLS on the HTTP interface
```

Die Registrierung als benannte Quelle ist unabhängig davon, ob dasselbe Warehouse als Federation-Engine gewählt wird. Eine Snowflake-Quelle auf einer DuckDB-Engine landet ein Replikat in DuckDB, nicht in Snowflake.

Cloud-Objekt-/Lake-Daten (Parquet-, CSV-, Iceberg-, Delta-Lake-Dateien auf S3 / GCS / R2) sind ein separater Quelltyp, der vor Ort angehängt wird, wenn die aktive Engine einen ATTACH-Connector für diesen Typ hat. Kein Replikat wird gelandet — die Engine scannt den Objektspeicher direkt. Zugangsdaten für diese Quellen gehen ebenfalls in `federation_hints`:

```yaml
sources:
  - id: r2-events
    type: parquet
    path: s3://my-bucket/events/2026/*.parquet
    federation_hints:
      access_key_id: ${env:R2_ACCESS_KEY}
      secret_access_key: ${env:R2_SECRET}
      account_id: ${env:R2_ACCOUNT_ID}     # Cloudflare R2 account (S3-compatible)
```

---

## Quellkonfigurationsfelder

Alle Quellen teilen eine gemeinsame Menge von Feldern. [tool-verified: `provisa/core/models.py` `Source` class, lines 138–204]

| Feld | Erforderlich | Standard | Beschreibung |
| ------- | ---------- | --------- | ------------- |
| `id` | Ja | — | Eindeutiger Bezeichner; alphanumerisch mit Bindestrichen/Unterstrichen |
| `type` | Ja | — | Quelltyp (siehe obige Tabellen) |
| `host` | Nein | `""` | Hostname oder IP |
| `port` | Nein | `0` | Portnummer |
| `database` | Nein | `""` | Datenbankname |
| `username` | Nein | `""` | Benutzername |
| `password` | Nein | `""` | Passwort; verwenden Sie `${env:VAR}` oder `${secret:NAME}` statt eines Literals (siehe unten) |
| `path` | Nein | `null` | Dateipfad oder Cloud-URI für dateibasierte und Objekt-/Lake-Quellen |
| `base_url` | Nein | `null` | Basis-URL für OpenAPI-Quellen |
| `pool_min` | Nein | `1` | Minimale Connection-Pool-Größe (REQ-052) |
| `pool_max` | Nein | `5` | Maximale Connection-Pool-Größe (REQ-052) |
| `use_pgbouncer` | Nein | `false` | Verbindungen über PgBouncer routen (REQ-053) |
| `pgbouncer_port` | Nein | `6432` | PgBouncer-Port (REQ-053) |
| `cache_enabled` | Nein | `true` | API-Response-Caching aktivieren |
| `cache_ttl` | Nein | `null` | Cache-TTL in Sekunden; erbt globalen Standard, wenn null |
| `cache_catalog` | Nein | `null` | Föderierter Katalog für API-Cache; Standard ist der eigene Katalog der Quelle |
| `cache_schema` | Nein | `api_cache` | Schema innerhalb des Cache-Katalogs |
| `naming_convention` | Nein | `null` | Überschreibt die globale Namenskonvention für diese Quelle (REQ-194) |
| `federation_hints` | Nein | `{}` | An die Federation-Engine übergebene Session-Eigenschaften und erweiterte Verbindungsparameter für Warehouse-Quellen (REQ-278, REQ-281) |
| `mapping` | Nein | `{}` | Typspezifische Connector-Einstellungen für NoSQL- und SaaS-Quellen (z. B. SharePoint `auth_type`, Salesforce `auth_type`, Splunk `use_token`) (REQ-251) |
| `allowed_domains` | Nein | `[]` | Quelle auf bestimmte Domänen beschränken; leer = uneingeschränkt |
| `description` | Nein | `""` | Menschenlesbare Beschreibung |

---

## Kafka-Quellen

Kafka-Topics werden separat unter `kafka_sources` konfiguriert, verschlüsselt nach der Quell-`id` einer registrierten `kafka`-Quelle. [tool-verified: `config/provisa.yaml` lines 138–151] (REQ-147)

```yaml
kafka_sources:

  - id: kafka-support
    topics:

      - id: tickets
        topic: support.tickets
        domain_id: sales-analytics
        description: "Inbound support tickets"
        default_window: 1h
        columns:

          - name: id
          - name: subject
          - name: status
          - name: created_at
```

| Feld | Beschreibung |
| ------- | ------------- |
| `id` | Muss der `id` einer Quelle mit `type: kafka` entsprechen |
| `topics[].id` | Logischer Name für dieses Topic innerhalb von Provisa |
| `topics[].topic` | Kafka-Topic-Name |
| `topics[].domain_id` | Domäne, zu der dieses Topic gehört |
| `topics[].description` | Menschenlesbare Beschreibung |
| `topics[].default_window` | Standard-Zeitfenster für Windowed-Abfragen (z. B. `1h`) (REQ-148) |
| `topics[].columns` | Spaltendefinitionen für das Topic-Schema (REQ-150) |

---

## Spaltensichtbarkeit

Das Feld `visible_to` auf jeder Spalte ist eine Liste von Rollen-IDs, die diese Spalte sehen können. [tool-verified: `provisa/core/models.py` `Column` class line 248; `config/provisa.yaml` lines 39–51]

```yaml
columns:

  - name: email
    visible_to: [admin]        # only admin role sees this column

  - name: region
    visible_to: [admin, analyst]  # both roles see this column
```

Spalten, die aus der `visible_to`-Liste einer Rolle ausgelassen sind, erscheinen nicht im GraphQL-Schema dieser Rolle und können nicht abgefragt oder in Filtern referenziert werden (REQ-039).

---

## Beziehungen

Beziehungen verbinden zwei registrierte Tabellen und erscheinen als verschachtelte Felder in GraphQL. [tool-verified: `provisa/core/models.py` `Relationship` class lines 323–343; `config/provisa.yaml` lines 103–110] (REQ-019)

```yaml
relationships:

  - id: orders-to-customers
    source_table_id: orders
    target_table_id: customers
    source_column: customer_id
    target_column: id
    cardinality: many-to-one
```

| Feld | Erforderlich | Beschreibung |
| ------- | ---------- | ------------- |
| `id` | Ja | Eindeutiger Bezeichner für diese Beziehung |
| `source_table_id` | Ja | Tabelle, die den Fremdschlüssel trägt |
| `target_table_id` | Ja | Referenzierte Tabelle; leer bei berechneten Beziehungen |
| `source_column` | Ja | Spalte auf der Quelltabelle |
| `target_column` | Ja | Spalte auf der Zieltabelle; leer bei berechneten Beziehungen |
| `cardinality` | Ja | `many-to-one` oder `one-to-many` (REQ-019) |
| `materialize` | Nein | Erstellt automatisch eine materialisierte Sicht für quellenübergreifende Joins (REQ-158). Bei einer junction-gestützten Kante deckt die Sicht die Zwei-Hop-Traversierung ab, nicht einen direkten Join (REQ-1586) |
| `refresh_interval` | Nein | MV-Refresh-Intervall in Sekunden (Standard: 300) |
| `target_function_name` | Nein | DB-Funktionsname für berechnete Beziehungen |
| `function_arg` | Nein | Welches Funktionsargument den Wert der Quellspalte erhält |
| `alias` | Nein | Menschenlesbarer Beziehungstyp (z. B. `WORKS_FOR`) |
| `graphql_alias` | Nein | Benennt das SDL-Feld, das diese Beziehung auf dem übergeordneten Typ offenlegt. Fehlt es, wird der Name aus dem `field_name` der Zieltabelle und der Beziehungskardinalität abgeleitet. [tool-verified: `provisa/compiler/schema_gen.py:1050`] |
| `disable_cypher` | Nein | Bei `true` wird diese Beziehung von den Cypher-Graphkanten ausgeschlossen |
| `source_json_key` | Nein | Extrahiert diesen Key aus der Quellspalte als JSON-Objekt vor dem JOIN |
| `via_table` | Nein | Registrierter Tabellenname der Junction, die diese Kante durchläuft. Das Setzen macht die Kante junction-gestützt; leer lassen macht sie zu einer Fremdschlüsselkante (REQ-1586) |
| `via_source_column` | Nein | Junction-Spalte, gepaart mit `source_column`. Kommagetrennt und positionsbezogen bei einem zusammengesetzten Schlüssel |
| `via_target_column` | Nein | Junction-Spalte, gepaart mit `target_column` |
| `via_type_column` | Nein | Diskriminator-Spalte, wenn eine Junction mehrere Beziehungstypen trägt |
| `via_type_value` | Nein | Der Diskriminatorwert, auf den diese Kante festgelegt ist |
| `via_label_source` | Nein | Welche Nominierung den Cypher-Typ benennt: `column` (der Diskriminatorwert), `table` (der Tabellenname der Junction) oder `fixed` (der deklarierte Alias). Alle werden in Upper-Snake-Case umgewandelt |

### Junction-gestützte Beziehungen

Eine assoziative Tabelle kann als erstklassige Cypher-Beziehung statt als Knoten deklariert werden, sodass ihre
eigenen Spalten zu den Attributen dieser Beziehung werden: (REQ-1586)

```yaml
relationships:

  - id: pets-bonded-pair
    source_table_id: pets
    target_table_id: pets
    source_column: id
    target_column: id
    cardinality: one-to-many
    via_table: pet_companions
    via_source_column: pet_id
    via_target_column: companion_pet_id
    via_type_column: relation_type
    via_type_value: bonded pair
    via_label_source: column
```

Die Junction ist eine registrierte Tabelle wie jede andere und muss registriert sein, bevor eine Beziehung sie
benennen kann. Deklarieren Sie sie einmal pro Diskriminatorwert: Drei Zeilen über `pet_companions` erzeugen
`BONDED_PAIR`, `LITTERMATE` und `SHARES_ENCLOSURE` als drei unterschiedliche Cypher-Typen, jeder mit den
verbleibenden Spalten der Junction-Zeile als Kanteneigenschaften. Die mitgelieferte Demo-Konfiguration
deklariert genau dies.

Eine Junction-Kante ist eine Cypher-Beziehung, kein GraphQL-Join-Feld: Der GraphQL-Join-Emitter baut
seine `ON`-Klausel für ein einzelnes Spaltenpaar und hat keinen Platz für den zweiten Hop, sodass Junction-Kanten
von der generierten SDL und von `pg_constraint` ausgeschlossen sind. [tool-verified: `provisa/compiler/schema_gen.py:304`]
Die Junction-Tabelle bleibt als eigenes Root-Feld abfragbar und wird aus der Knotenseite des
Cypher-Graph-Schemas entfernt, sodass sie nie als Knotenbezeichnung erscheint.

`materialize: true` funktioniert auf einer Junction-Kante, und was sie materialisiert, ist die Traversierung statt
eines direkten `pets`-zu-`pets`-Joins: Die Sicht hält den Quell-Hop, den Junction-Hop, den Diskriminator
und die eigenen Spalten der Junction neben denen des Ziels. Da die Junction ein drittes Bein des Joins ist,
wird beurteilt, ob die Kante quellenübergreifend ist, über alle drei Tabellen hinweg — eine Junction in einer anderen Quelle
als die beiden, die sie verbindet, wird materialisiert, selbst wenn diese beiden übereinstimmen. Eine Deklaration materialisiert einen
Kantentyp, sodass eine für `bonded pair` gebaute Sicht nie eine `littermate`-Traversierung beantwortet.

Kardinalitätswerte [tool-verified: `provisa/core/models.py` `Cardinality` enum, lines 79–81]:

- `many-to-one` — jede Quellzeile bildet auf eine Zielzeile ab (FK auf PK)
- `one-to-many` — jede Quellzeile bildet auf mehrere Zielzeilen ab (Umkehrung des Obigen)

---

## Sicherheit-auf-Zeilenebene-Regeln

RLS-Regeln injizieren `WHERE`-Klauseln zur Abfragezeit, bezogen auf eine Rolle und optional auf eine Tabelle oder Domäne. [tool-verified: `provisa/core/models.py` `RLSRule` class lines 391–395; `config/provisa.yaml` lines 128–131] (REQ-041)

```yaml
rls_rules:

  - table_id: orders          # applies to orders table only
    role_id: analyst
    filter: "region = current_setting('provisa.user_region')"

  - domain_id: sales-analytics  # applies to every table in domain (REQ-402)
    role_id: analyst
    filter: "tenant_id = current_setting('provisa.tenant_id')"
```

Existieren sowohl eine Regel auf Domänenebene als auch auf Tabellenebene für dieselbe Rolle, hat die Regel auf Tabellenebene Vorrang (REQ-403).

| Feld | Erforderlich | Beschreibung |
| ------- | ---------- | ------------- |
| `table_id` | Bedingt | Tabelle, auf die die Regel angewendet wird; schließt sich mit `domain_id` gegenseitig aus |
| `domain_id` | Bedingt | Domäne, auf die die Regel angewendet wird; gilt für alle Tabellen in der Domäne (REQ-402) |
| `role_id` | Ja | Rolle, für die diese Regel gilt |
| `filter` | Ja | SQL-Prädikat, injiziert in `WHERE`; kann Session-Variablen referenzieren (REQ-041) |

---

## Funktionen und Webhooks

### DB-Funktionen

Tracken Sie eine Datenbankfunktion und legen Sie sie als GraphQL-Abfrage oder -Mutation offen. [tool-verified: `provisa/core/models.py` `Function` class lines 423–438; `config/provisa.yaml` lines 152–164] (REQ-205)

Datenbankquellen können ihre gespeicherten Prozeduren und Funktionen auch automatisch aus dem Vendor-Katalog erkennen (`pg_proc`, `information_schema.routines`, oder Vendor-Äquivalente), wodurch die manuelle Registrierung jeder einzelnen entfällt. Discovery liest `prokind` und `provolatile`: unveränderliche/stabile Funktionen registrieren sich als parametrisierte Relationen (Prozedurargumente werden zu Abfrageparametern, dieselbe Form wie OpenAPI-GET-Tabellen), und volatile Prozeduren registrieren sich als Mutations/getrackte Funktionen. Erkannte Routinen durchlaufen die Stage-2-Governance identisch zu handregistrierten. [tool-verified: `provisa/api/admin/introspect.py:541`, `provisa/api/admin/introspect.py:593`] (REQ-887)

```yaml
functions:

  - name: get_customers_by_region
    source_id: sales-pg
    schema: public
    function_name: get_customers_by_region
    returns: customers
    domain_id: sales-analytics
    description: "Returns customers filtered by region"
    visible_to: [admin, analyst]
    kind: query
    arguments:

      - name: p_region
        type: String
```

| Feld | Erforderlich | Standard | Beschreibung |
| ------- | ---------- | --------- | ------------- |
| `name` | Ja | — | GraphQL-Feldname |
| `source_id` | Ja | — | Quelle, die die Funktion enthält |
| `schema` | Nein | `public` | Datenbankschema |
| `function_name` | Ja | — | Tatsächlicher Datenbankfunktionsname |
| `returns` | Ja | — | Registrierte Tabellen-ID, die die Funktion zurückgibt (REQ-207) |
| `arguments` | Nein | `[]` | Liste von `{name, type}`-Argumentdefinitionen (REQ-211) |
| `visible_to` | Nein | `[]` | Rollen, die diese Funktion aufrufen können |
| `writable_by` | Nein | `[]` | Rollen, die dies als Mutation aufrufen können |
| `domain_id` | Nein | `""` | Domäne, zu der diese Funktion gehört |
| `description` | Nein | `null` | GraphQL-Feldbeschreibung |
| `kind` | Nein | `mutation` | `"query"` oder `"mutation"` (REQ-205) |

### Webhooks

Legen Sie einen externen HTTP-Endpunkt als GraphQL-Abfrage oder -Mutation offen. [tool-verified: `provisa/core/models.py` `Webhook` class lines 441–455; `config/provisa.yaml` lines 166–178] (REQ-209)

```yaml
webhooks:

  - name: notify_support
    url: http://localhost:9999/notify
    method: POST
    timeout_ms: 3000
    domain_id: sales-analytics
    description: "Send a support notification"
    visible_to: [admin]
    kind: mutation
    arguments:

      - name: message
        type: String
```

| Feld | Erforderlich | Standard | Beschreibung |
| ------- | ---------- | --------- | ------------- |
| `name` | Ja | — | GraphQL-Feldname |
| `url` | Ja | — | Webhook-Endpunkt-URL |
| `method` | Nein | `POST` | HTTP-Methode |
| `timeout_ms` | Nein | `5000` | Anfrage-Timeout in Millisekunden |
| `returns` | Nein | `null` | Registrierte Tabellen-ID, oder null für Inline-Typ |
| `inline_return_type` | Nein | `[]` | Liste von `{name, type}`-Feldern für benutzerdefinierte Rückgabeformen (REQ-210) |
| `arguments` | Nein | `[]` | Liste von `{name, type}`-Argumentdefinitionen |
| `visible_to` | Nein | `[]` | Rollen, die diesen Webhook aufrufen können |
| `domain_id` | Nein | `""` | Domäne, zu der dieser Webhook gehört |
| `description` | Nein | `null` | GraphQL-Feldbeschreibung |
| `kind` | Nein | `mutation` | `"query"` oder `"mutation"` |

---

## Authentifizierung

Auth wird unter dem Key `auth` konfiguriert. [tool-verified: `provisa/core/models.py` `AuthConfig` class lines 467–477] (REQ-120)

| Provider | Beschreibung |
| ---------- | ------------- |
| `none` | Keine Authentifizierung; alle Anfragen werden als `default_role` behandelt |
| `firebase` | Firebase Authentication; erfordert `project_id` und `service_account_key` (REQ-121) |
| `keycloak` | Keycloak OIDC (REQ-122) |
| `oauth` | Generisches OAuth 2.0 (REQ-123) |
| `simple` | Benutzername/Passwort ohne externen Provider (REQ-124) |

```yaml
auth:
  provider: firebase
  assignments_source: provisa   # "claims" or "provisa"
  default_role: analyst
  default_assignments:

    - role_id: analyst
      domain_id: "*"
  firebase:
    project_id: ${env:FIREBASE_PROJECT_ID}
    service_account_key: ${env:FIREBASE_SERVICE_ACCOUNT_KEY}
```

`assignments_source: claims` liest Rollenzuweisungen aus JWT-Claims. `assignments_source: provisa` liest sie aus Provisas eigenem Zuweisungs-Store. [tool-verified: `provisa/core/models.py` line 476] (REQ-551)

---

## Ausführungs-Routing

**Direkte Ausführung** — Einzelquellen-RDBMS-Abfragen routen zum nativen Treiber für Latenz unter 100 ms (REQ-027). Quellen benötigen sowohl einen `SOURCE_TO_DIALECT`-Eintrag als auch einen `SOURCE_TO_CONNECTOR`-Eintrag, um diesen Pfad zu unterstützen (REQ-229).

**Föderierte Ausführung** — Mehrquellen-Abfragen und Quellen ohne direkten Treiber routen über die Federation-Engine (REQ-028). Provisa enthält eine eingebettete Federation-Engine; verweisen Sie für großangelegte Deployments auf Ihren eigenen kompatiblen Cluster (REQ-226).

**Statistiken** — Bei der Registrierung führt Provisa `ANALYZE` gegen jede veröffentlichte Tabelle aus, um den kostenbasierten Optimizer zu initialisieren (Zeilenanzahlen, Null-Anteil, eindeutige Werte, Min/Max). Fehler werden protokolliert und blockieren die Registrierung nicht (REQ-275).

---

## Graph- & Semantic-Quellen

### Neo4j

Registrieren Sie eine Neo4j-Graphdatenbank als abfragbare Quelle. Stewards verfassen Cypher-Abfragen, die skalare Werte projizieren; Provisa cacht Ergebnisse und legt sie als GraphQL-Typen offen (REQ-295).

Cypher-Abfragen müssen Property-Zugriffe in der `RETURN`-Klausel verwenden (`RETURN n.id AS id, n.name AS name`) — die Rückgabe von Knotenobjekten wird bei der Registrierung abgelehnt (REQ-296).

#### Konfigurationsdatei-Registrierung (REQ-1668)

Deklarieren Sie eine `neo4j`-Quelle und ihre Tabellen in YAML. Jede Tabelle benötigt ein `query_template` (das Cypher, das ihre Zeilen erzeugt) und typisierte Spalten. Der Key `query_template` ist unter jedem anderen Quelltyp ungültig. [tool-verified: `provisa/core/config_loader.py:456-511`]

Eine Quelle benötigt `host`, `port` und `database`. [tool-verified: `provisa/core/config_loader.py:456-468`] Zeilen werden abgerufen, indem `{"statements": [{"statement": <cypher>}]}` an `/db/<database>/tx/commit` gePOSTet wird (die Neo4j-HTTP-Transaktions-API). Eine Antwort mit nicht-leerer `errors`-Liste wird als fehlgeschlagene Abfrage behandelt, nicht als leeres Ergebnis. [tool-verified: `provisa/neo4j/source.py:71-82`, `provisa/api_source/caller.py:344-347`, `provisa/api_source/normalizers.py:49-74`]

Jede Spalte benötigt `data_type`. Der Loader bildet Konfigurationstypen auf den zur Abfragezeit verwendeten API-Spaltentyp ab [tool-verified: `provisa/neo4j/persist.py:31-64`]:

| Konfigurations-`data_type` | API-Typ |
|---|---|
| `varchar`, `text`, `string`, `char` | string |
| `integer`, `int`, `bigint`, `smallint` | integer |
| `float`, `double`, `real`, `decimal`, `numeric`, `number` | number |
| `boolean`, `bool` | boolean |
| `json`, `jsonb` | jsonb |

`varchar(N)` und `decimal(10,2)` werden akzeptiert — der Basistyp vor der Klammer wird verwendet.

Die Registrierung persistiert eine `api_sources`-Zeile und eine `api_endpoints`-Zeile pro Tabelle, sodass die Tabellen einen Neustart überstehen, ohne die Datei erneut zu lesen. Die Admin-REST-Endpunkte unter `/admin/sources/neo4j` schreiben dieselben Zeilen. [tool-verified: `provisa/neo4j/persist.py:77-120`]

```yaml
sources:
  - id: graph
    type: neo4j
    host: neo4j
    port: 7474
    database: neo4j
    cache_ttl: 300

tables:
  - source_id: graph
    schema: neo4j
    table: person_skills
    query_template: >-
      MATCH (p:Person)-[:HAS_SKILL]->(s:Skill)
      RETURN p.name AS name, s.skill AS skill, p.experience AS years
    columns:
      - name: name
        data_type: varchar
      - name: skill
        data_type: varchar
      - name: years
        data_type: integer
```

#### Register Table in der UI (REQ-1670)

Eine neo4j-Quelle hat keine Tabellen zum Auflisten, daher fragt das Register-Table-Formular nach der Tabelle, statt eine anzubieten. [tool-verified: `provisa-ui/src/pages/tables/RegisterTableForm.tsx` (`isNeo4j`)]

1. Wählen Sie die neo4j-Quelle und eine Domäne. Die Schema- und Tabellenauswahl, die Discover-Checkbox und die Watermark-Auswahl erscheinen nicht; die Quelle wird nie introspiziert.
2. Geben Sie einen Tabellennamen und das Cypher ein. Das Cypher muss Skalare projizieren (`RETURN a.name AS name`); eine Projektion, die einen Knoten oder eine Liste zurückgibt, wird als Fehler gemeldet.
3. Drücken Sie Preview. Das Formular führt das Cypher mit `LIMIT 5` über die `neo4jPreview`-GraphQL-Abfrage aus und befüllt die Spaltenliste aus den zurückkommenden Zeilen, typisiert als `text`, `integer`, `double`, `boolean` oder `json`. [tool-verified: `provisa/api/admin/_neo4j_registration.py` `preview_neo4j`] Eine fehlgeschlagene Vorschau lässt das Cypher im Editor und zeigt die Meldung.
4. Passen Sie Sichtbarkeit, Aliase oder Maskierung wie bei jeder Tabelle an und registrieren Sie dann. Das Formular verweigert das Absenden, bis eine Vorschau die Spalten typisiert hat, und der Server lehnt eine neo4j-Tabelle ohne Cypher ab (`schema.neo4j_query_required`). [tool-verified: `provisa/api/admin/schema_mutation_ops.py` `persist_neo4j_registration`]

Das Cypher wird mit der Tabelle als `queryTemplate` gespeichert, erscheint in der Lese-Ansicht der Tabelle und persistiert genau wie eine Konfigurationsdatei-Registrierung: eine `api_sources`-Zeile und eine `api_endpoints`-Zeile, die der nächste Start hydriert. Das Bearbeiten der Tabelle persistiert ein bearbeitetes Cypher erneut.

#### Admin-REST-Registrierung

```bash
# Register via admin API (no YAML config required)
POST /admin/sources/neo4j
{
  "source_id": "graph",
  "host": "neo4j",
  "port": 7474,
  "database": "neo4j"
}

# Register a table (preview + validate before persisting)
POST /admin/sources/neo4j/graph/tables
{
  "table_name": "person_skills",
  "cypher": "MATCH (p:Person)-[:HAS_SKILL]->(s:Skill) RETURN p.name AS name, s.skill AS skill, p.experience AS years",
  "ttl": 300
}
```

Der Preview-Endpunkt (`POST /admin/sources/neo4j/{id}/preview`) gibt Beispielzeilen zurück und blockiert die Registrierung, wenn das Cypher Knotenobjekte zurückgibt (REQ-296).

### SPARQL

Registrieren Sie jeden SPARQL-1.1-konformen Triple-Store (Apache Jena Fuseki, Virtuoso, Stardog usw.) als abfragbare Quelle (REQ-297).

Abfragen müssen `SELECT`-Abfragen sein. Variablennamen in der `SELECT`-Klausel werden automatisch zu Spaltennamen (REQ-297).

```bash
# Register via admin API
POST /admin/sources/sparql
{
  "source_id": "knowledge-graph",
  "endpoint_url": "http://fuseki:3030/ds/sparql",
  "default_graph_uri": "http://example.org/graph"
}

# Register a table (executes LIMIT 5 probe to validate and infer columns)
POST /admin/sources/sparql/knowledge-graph/tables
{
  "table_name": "product_categories",
  "sparql_query": "SELECT ?product ?label ?category WHERE { ?product a :Product ; rdfs:label ?label ; :hasCategory ?category . }",
  "ttl": 600
}
```

Beide Connectors verwenden die API-Source-Cache-Pipeline — Ergebnisse werden in PostgreSQL mit konfigurierbarer TTL gespeichert, wodurch sie für quellenübergreifende föderierte JOINs verfügbar werden (REQ-295, REQ-297, REQ-299).

---

#### Konfigurationsdatei- und UI-Registrierung (REQ-1683)

Der `host` einer `sparql`-Quelle ist ihre SPARQL-Endpunkt-URL (das Sources-Formular speichert es auf dieselbe Weise). Jede Tabelle darunter trägt `query_template`, ein SELECT, dessen Variablen die Spalten sind; jede Bindung ist `text`. [tool-verified: `provisa/core/config_loader.py` `_validate_neo4j_sources`, `_handle_sparql_table`]

```yaml
sources:
- id: sparql-demo
  type: sparql
  host: http://localhost:23030/provisa/query
tables:
- source_id: sparql-demo
  domain_id: shelter
  schema: sparql
  table: volunteer
  query_template: >-
    PREFIX s: <http://provisa.dev/shelter#>
    SELECT ?volunteer_id ?name WHERE { ?v a s:Volunteer ; s:id ?volunteer_id ; s:name ?name }
  columns:
  - { name: volunteer_id, data_type: text, visible_to: [org_admin] }
  - { name: name, data_type: text, visible_to: [org_admin] }
```

Register Table funktioniert genauso wie bei Neo4j: Wählen Sie die Quelle, geben Sie einen Tabellennamen und das SELECT ein, drücken Sie Preview (die `sparqlPreview`-Abfrage führt es mit `LIMIT 5` aus und befüllt die Spaltenliste), dann registrieren. Die Registrierung persistiert eine `api_sources`-Zeile und eine `api_endpoints`-Zeile (formularkodiertes POST an den Endpunktpfad, `sparql_bindings`-Normalisierer), dieselben Zeilen, die eine Konfigurationsdatei-Registrierung schreibt, und die native Engine landet die Zeilen über dieselbe Fetch-Kette wie Neo4j. [tool-verified: `provisa/api/admin/_query_api_registration.py`, `provisa/sparql/persist.py`]

## Verbindungsbeispiele

### PostgreSQL

```yaml
- id: sales-pg
  type: postgresql
  host: postgres
  port: 5432
  database: provisa
  username: provisa
  password: ${env:PG_PASSWORD}
```

### Snowflake

```yaml
- id: analytics-sf
  type: snowflake
  host: org.snowflakecomputing.com
  port: 443
  database: ANALYTICS
  username: svc_provisa
  password: ${env:SNOWFLAKE_PASSWORD}
  federation_hints:
    account: myorg-myaccount
    warehouse: COMPUTE_WH
```

### Databricks

```yaml
- id: lakehouse-db
  type: databricks
  host: my-workspace.azuredatabricks.net
  password: ${env:DATABRICKS_TOKEN}
  federation_hints:
    http_path: /sql/1.0/warehouses/xxxx
```

### MongoDB

```yaml
- id: reviews-mongo
  type: mongodb
  host: mongodb
  port: 27017
  database: provisa
  username: ""
  password: ""
```

### Quellenübergreifende Abfrage

```graphql
{
  orders(where: {region: {eq: "us"}}) {
    id
    amount
    customers {       # PostgreSQL
      name
      email
    }
    productReviews {  # MongoDB (federated)
      rating
      comment
    }
  }
}
```

Einzelquellen-Anteile routen direkt (REQ-027). Quellenübergreifende JOINs föderieren mit automatischer Typkonvertierung (REQ-028, REQ-552).
