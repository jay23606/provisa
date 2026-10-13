# Optimistic benchmark: three-device methodology

DRAFT for review. Nothing here has been provisioned or run.

The optimistic benchmark measures Provisa's own ceiling per transport: one row, one column, no filter, the Postgres `orders` table. This revision moves it from one shared machine to three, so no figure carries another program's CPU. The published figures are measured with telemetry off; the same points are measured again with telemetry on, to measure what telemetry costs.

## What runs where

| Device | Runs | Nothing else |
|---|---|---|
| 1, server | Provisa: its worker processes, every listener (HTTP, pgwire, Flight, Bolt, gRPC), its in-process engine; `server_cpu_agent.py` | No database, no collector, no load generator |
| 2, client | `run_benchmark.py --optimistic` (the load generator) | No Provisa, no source |
| 3, backends | The Postgres source (`orders`), the control-plane Postgres, Redis (the shared response cache), the OTel collector and the OTel-to-table processing (otlp2parquet, otlp2sql); the host agent for container CPU | No Provisa, no load generator |

Redis is listed on device 3; it is a server Provisa reaches over the network, as it would be in production. Moving it to device 1 is the alternative: state which in the report.

All three are in one zone. A compact placement policy keeps the round trip stable between runs.

## Provisioning

There is no `terraform/perf` today: the single perf VM was made by hand. Proposed: a `terraform/perf` module that creates the three instances from variables (machine type per device, zone, image), one compact placement policy, and a firewall rule that opens each device's ports to the other two only. The maintainer applies it. No public addresses are opened beyond SSH.

Per device, after provisioning:

- **Device 3:** `docker compose -f demo/named/perf/docker-compose.yml up -d postgresql redis seeder` plus the control-plane Postgres and the collector services (to be added to that compose file, as `profiles` so the single-host run is unchanged). Wait for `seeder` to exit 0.
- **Device 1:** the repository at the commit under test. `orchestrate.sh` gains a `serve` mode that starts Provisa only, with the source, Redis, control-plane and collector addresses pointing at device 3. `config.yaml` already reads the source hosts from `PROVISA_BENCH_*_HOST`. Then `server_cpu_agent.py --pid <provisa> --listen <device-1 private address>:9555`.
- **Device 2:** the repository at the same commit, and a contract whose endpoints name device 1's private address. The contract already takes a host and port per transport.

## Reported per device

Read off each machine by the host agent at the start of the run, never typed in:

- the machine type (GCE metadata `machine-type`) and the zone (metadata `zone`);
- physical cores and threads per core (`lscpu`);
- the link: the NIC type and the machine type's egress bandwidth tier;
- the measured round trip, device 2 → device 1 and device 1 → device 3: the median of 100 TCP connects to the service port, with its p99.

CPU per step, each from its own device:

- device 1: Provisa's CPU per request (`server_cpu_agent.py`), and its CPU in cores;
- device 2: the load generator's CPU in cores and `client_limited`. A client-limited step is a measurement of the client and is never published;
- device 3: the CPU of each container (Postgres, control-plane Postgres, Redis, collector, otlp2parquet or otlp2sql), so a backend bottleneck shows.

## Telemetry off and on

Each point is measured with telemetry off and with telemetry on, on the same three devices. One setting per run, `PROVISA_BENCH_TELEMETRY=off|on`, and the report names it.

- **Off: the published figure.** No exporter endpoint, and `observability.sample_rate: 0`, so no span is recorded or exported. Its caption: "Telemetry OFF".
- **On: the impact, not published.** The exporter endpoint is the collector on device 3, at the sample rate and trace detail Provisa ships with. Provisa pays for creating and exporting spans; receiving and storing them is on device 3.

The internal report gives the difference between the two per transport: requests per second, p99, and Provisa CPU per request. Only the off figures are published.

## Warm-up, repetitions and spread

- **Warm-up:** after Provisa reports every worker serving, one 60 s step at the highest concurrency, per transport, discarded. It warms the plan cache, the response cache, connection pools and the source's buffers.
- **Ramp:** the contract's steps (1, 16, 64, 256 connections), 30 s each.
- **Repetitions:** 5 per point, with off and on alternating (off, on, off, on, ...) so drift over the session falls on both alike. Provisa is restarted between runs, because the sample rate is fixed at start.
- **Spread:** each figure is the median of the 5, with the minimum and maximum beside it.

## The published point

Per transport, with telemetry off: the step with the highest throughput that had no errors and was not client-limited. At that step the report gives:

- requests per second, median and p99 latency, and errors (0);
- Provisa CPU per request;
- client CPU and source CPU;
- the three devices and the network as above;
- the caption: the read path, "single source, direct read", and "Telemetry OFF". It names no federation engine: the optimistic request reads one source, from the response cache or directly from Postgres on a miss, so no engine is in its path. The engine is stated per run only for the sizing knob runs, where requests do reach it;
- the commit, the contract, and the raw results.

The language and transport pairs are those already published: SQL over pgwire (cached and uncached, side by side), SQL over Arrow Flight, GraphQL over HTTP, Cypher over Bolt, gRPC, REST and JSON:API.

## Harness changes this needs

1. `orchestrate.sh serve`: Provisa only, backend addresses from the environment, telemetry from `PROVISA_BENCH_TELEMETRY`, no no-op collector.
2. Compose profiles on device 3 for the control-plane Postgres, the collector and otlp2parquet/otlp2sql.
3. The host agent grows from `server_cpu_agent.py`. It stays read-only and needs an explicit `--listen`. It adds machine facts, container CPU (on device 3) and a round-trip probe to a named host and port.
4. `run_benchmark.py`: a `--source-cpu-url` (device 3's agent) beside `--server-cpu-url`, a timed warm-up step, repetitions with off and on alternating, and the per-device block in the report.
5. `terraform/perf`, if approved.

## Open for review

- Redis on device 3 (proposed) or device 1.
- Whether `terraform/perf` is wanted, or the three instances are made by hand from a written list.
- The machine types: 16 physical cores for device 1 was the reference before. Devices 2 and 3 must not be the limit; their CPU in the report shows whether they were.
