# Stage E — PostgreSQL confirms H1 resource-retention chain

Status: contributor-only runtime evidence for issue #107. Production source remains unchanged.

## Setup

- branch: `fix/data-service-saturation`
- reviewed baseline: `ed01be9056776c107ab76a404c328a4fed19f529`
- dedicated DB: `inalpha_issue107`
- one data worker
- hardened contributor wrapper
- fake venue: Binance only
- provider mode: async
- provider delay: 10s
- `application_name=issue107-data`
- snapshot scheduler forced disabled

The Stage-E preflight passed with a clean server and pool initially at 2/10.

## Application-side snapshot during provider wait

The capture observed:

```text
active=10
started=10
pool_available=0
pool_waiting=1
```

The extra pool waiter is compatible with the DB-backed health/control activity occurring while all ten backfill requests hold pool capacity.

## PostgreSQL-side snapshot

`pg_stat_activity` returned exactly ten `issue107-data` sessions. Every session was:

```text
state           = idle in transaction
wait_event_type = Client
wait_event      = ClientRead
```

Every session's last query was the same current-main `latest_bar_ts()` lookup shape:

```sql
SELECT max(ts) AS m
FROM bars
WHERE venue = $1
  AND symbol = $2
  AND timeframe = $3
  AND ts <= $4
```

Grouped result:

```text
idle in transaction | Client | ClientRead | 10 sessions
```

The transaction ages were already increasing while the deterministic fake provider was still sleeping.

## Cross-layer correlation

The data wrapper logged ten fake-provider starts before release, while PostgreSQL simultaneously showed ten open transactions whose last command was the `latest_bar_ts()` SELECT.

This demonstrates the current-main lifetime directly:

```text
/backfill/bars
→ checkout DB connection
→ latest_bar_ts SELECT
→ transaction remains open / connection remains retained
→ external provider await
→ provider wait consumes essentially all DB-pool capacity
```

This is stronger than inferring H1 from HTTP latency alone.

During the same wait, non-DB `/openapi.json` requests continued to return immediately, while DB-backed `/health` requests accumulated multi-second server-side durations until provider completion released capacity.

## Interpretation

H1 is now confirmed across all relevant controlled layers:

1. pool=2 deterministic diagnostic reproduces DB-backed starvation while ASGI remains responsive;
2. normal pool=10 real-TCP D10 reproduces health timeouts at saturation;
3. D12 shows requests queueing above the pool limit and backfill latency doubling;
4. PostgreSQL directly shows one `idle in transaction` session per blocked provider request, with `latest_bar_ts()` as the last query.

This establishes H1 as materially relevant under the current one-worker normal-pool topology.

It still does not justify applying a production patch before completing the planned remaining baseline checks that test retry/cancellation persistence, thread-backed work, worker topology, factor amplification, runner alignment and sustained mixed workloads.

## Decision impact

- H1 structural mechanism: **confirmed**
- H1 materiality in normal pool=10: **strongly confirmed in controlled baseline**
- Candidate A: **leading candidate, still not applied**
- production code changed: **no**
- next step: Stage F H9/H10 timeout/cancellation persistence, async mode first, then thread mode if needed
