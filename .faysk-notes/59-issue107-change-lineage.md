# Issue #107 — Change Lineage Since Creation

**Purpose:** separate the original June 25 failure report from mitigations that landed afterward, so the runtime baseline tests current `main` rather than reproducing already-fixed historical behavior.

**Production impact:** none.

---

## 1. Issue birth and the retry commit

Issue #107 was created at:

```text
2026-06-25 04:00:12 UTC
```

Its `已做` section points to short SHA:

```text
09e521b
```

That commit is resolvable as:

```text
09e521b46e96b7c155ad103707fe0779b80520d8
fix(factor): DataClient GET /bars 连接级瞬时失败有界重试
2026-06-25 03:45:58 UTC
```

So the issue was opened about fourteen minutes after the bounded-retry change and explicitly describes the remaining problem as **sustained overload that retries cannot solve**.

The patch adds:

```text
GET /bars attempts = 3
backoff after first failure = 0.25s
backoff after second failure = 0.6s
retry only httpx.RequestError
HTTP 4xx/5xx are not retried
exhaustion → DATA_SERVICE_UNREACHABLE
```

The exact issue-linked commit lives on a history that later diverged from current `main`. Current searchable `main` contains the same bounded-retry change under commit `358f3557f2593c2f673b460bd47e53a2b17d4326`.

Do not treat the changed SHA as a changed requirement: the behavior remains present in current code.

---

## 2. Same-day panel freshness mitigation

Later on June 25, current-main history gained:

```text
29b9fa3271180edcbcaa18c8e89ca78db38bd3c9
fix(factor): panel_score ... fresh=False (#103 CR)
```

The capacity-relevant part changed panel symbol fetches from live/fresh behavior to:

```text
fresh=False
→ read data-service DB cache
→ no per-symbol backfill inside panel_score
```

The commit message explicitly describes the prior behavior as an N-symbol backfill avalanche, with yfinance serialization + 60s timeout creating mixed freshness.

This means the original #107 phrase:

```text
agent 横截面查询(多标的并发 backfill)
```

is no longer a literal description of current `panel_score` behavior.

Panel remains useful as a control/DB-read workload, but it should not be the primary current-main reproduction of concurrent **backfill** pressure.

---

## 3. June 29 panel fan-out cap

Current main then gained:

```text
69ad27ed94a72506b62d89d2ed36886a2886e01a
fix(factor): panel universe 加并发上限 + 硬上限,治 indexCode 请求风暴 (#110 CR major)
```

This added:

```text
_PANEL_FETCH_CONCURRENCY = 16
_MAX_PANEL_SYMBOLS = 500
```

and wrapped per-symbol `/bars` work in an `asyncio.Semaphore(16)`.

The motivating failure was an index universe resolving to hundreds of symbols and an unbounded `asyncio.gather` producing up to ~500 concurrent data-service HTTP calls.

Therefore two original #107 candidate actions are now partly obsolete for panel specifically:

```text
"bound panel N-symbol gather"
→ already implemented at 16

"avoid panel per-symbol backfill storm"
→ already mitigated by fresh=False
```

This is why our first PR must not add a second panel semaphore merely because the original issue suggested one.

---

## 4. June 30 incremental backfill

Current main then gained:

```text
d4f56d31cf21a7f4b3eeda07d66e06ca5f520432
fix(data): backfill 增量续拉 + 永续符号现货价格 proxy
```

The capacity-relevant change made `/backfill/bars` resume from the latest persisted bar instead of refetching the full requested window on every call:

```text
latest_bar_ts(..., upto=to_ts)
→ cursor = cached latest when available
→ refetch final candle intentionally
→ continue only missing tail
```

The commit explicitly states that full-window refetches were causing frequent timeout for long windows and that the new behavior preserves tail freshness.

This substantially reduces repeated backfill cost, but does **not** introduce service-level admission control or change the route-scoped DB connection lifetime across provider I/O.

So current #107 reproduction should not assume every repeated fresh call refetches its whole historical window.

---

## 5. Later venue/provider changes also changed pressure shape

On July 13, Baostock quota work added tighter minute-window limits and cache/incremental behavior for that source (`1d96e1f...`).

On July 20–21, A-share routing moved from the historical `akshare` venue naming to `baostock`.

Current connectors also contain process-local serialization/throttling behavior for yfinance/Baostock-like synchronous provider paths.

Therefore provider pressure in current main is not identical to the provider mix that existed when #107 was opened.

This reinforces our fake-provider matrix approach:

```text
async fake
→ isolate DB/resource ordering

thread fake
→ model sync-SDK/to_thread persistence

per-venue counters
→ detect moved bottleneck
```

without load-testing real provider APIs.

---

## 6. `DATA_SERVICE_UNREACHABLE` has also represented non-capacity faults

A later self-host fix (`e4d7f7d48d83a62b3c0ea6e5694c2845b7933ad4`, merged via PR #154) fixed missing inter-service URLs that made factor fall back to `localhost:8001` **inside its own container**, also producing `failed to reach data-service` / 502 symptoms.

That is not #107's sustained-capacity root cause, but it is useful evidence about the error code:

```text
DATA_SERVICE_UNREACHABLE / "failed to reach data-service"
!=
proof of one specific capacity mechanism
```

It can represent at least:

```text
real connection refusal
read/connect timeout under pressure
service restart blip
misrouted service URL
other httpx RequestError classes
```

Our local factor wrapper + no-load target checker deliberately eliminate the routing-misconfiguration class before the capacity benchmark starts.

---

## 7. What remains genuinely open on current main

Static review still finds these original/current concerns unresolved or evidence-gated:

```text
data-side expensive-backfill admission control      absent
/backfill DB lease across external provider I/O     still present
runner global staggering/throttle                   not selected/currently absent as #107 fix
macro cold fan-out                                   still potentially concurrent
same-key in-flight coalescing                        not generally present cross-service
factor HTTP client lifetime/churn                    still measurable hypothesis
```

But none of those facts alone says which one causes the current issue-level failure.

---

## 8. Runtime consequence

The baseline must answer a narrower question than the original issue text:

> After the panel and incremental-backfill mitigations that landed after #107 was opened, can current `main` still reproduce sustained agent + runner pressure, and what resource now degrades first?

That is why the authoritative workload is no longer simply "run panel hard":

```text
low-level backfill/resource proof
→ live factor/macro cold fan-out
→ runner-like fresh polling
→ mixed burst
→ sustained O1 cross-sectional unique-symbol workload
```

Panel remains a useful historical/context control but is not assumed to be the current dominant backfill generator.

---

## 9. PR wording guard

If a fix is eventually selected, the PR should distinguish:

```text
already mitigated before our contribution
vs
measured remaining bottleneck
vs
our actual change
```

Do not write a PR narrative implying we introduced panel concurrency bounds, panel `fresh=False`, or incremental backfill if those are existing upstream work.

A strong eventual narrative would look like:

```text
#107 originally reported a broader overload combination.
Since then upstream already bounded panel fan-out and made backfill incremental.
On current main, our controlled baseline still reproduced <measured failure> because <measured mechanism>.
This PR changes only <smallest selected mechanism> and preserves the existing mitigations/invariants.
```

That makes the contribution accurately additive rather than taking credit for historical fixes.
