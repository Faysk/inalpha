# Issue #107 — Runtime Readiness Static Validation

**Status:** completed static preflight against current reviewed upstream before local execution.

**Purpose:** verify that the prepared diagnostics actually match current schemas, auth rules, service test conventions and supported venue/timeframe combinations before spending time debugging false negatives on the contributor machine.

This note does **not** replace runtime execution. It only reduces avoidable harness/setup mistakes.

---

## 1. Reviewed upstream baseline

At this pass the reviewed upstream `main` is still:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

The contribution branch must still be compared to fresh `upstream/main` immediately before execution. If upstream moves, this validation becomes historical and the sensitive paths must be re-read.

---

## 2. Data pytest integration shape matches our diagnostics

Current `services/data/pyproject.toml` uses:

```text
pytest-asyncio
asyncio_mode = auto
strict markers
integration marker declared
```

Therefore the contributor async diagnostics can be ordinary `async def test_*` functions with:

```python
pytestmark = pytest.mark.integration
```

without adding per-test `@pytest.mark.asyncio` decorators.

Current data tests also use the **real application lifespan / real shared DB pool** and replace connectors through `connectors._base._REGISTRY`.

That matches the design of:

```text
test_backfill_pool_pressure_draft.py
test_candidate_a_regression_draft.py
```

The diagnostics are not inventing a different application wiring model merely to make H1 easier to prove.

---

## 3. Authentication assumptions are valid

`data-service` auth requires:

```text
Authorization: Bearer <JWT>
valid configured HMAC algorithm
valid signature/expiry
sub claim
```

`email` is optional.

It explicitly rejects `token_use=session`, but normal service-style JWTs without that claim are accepted.

Therefore the generated contributor probe tokens containing `sub` + `exp` (and optional email/iat) match the current API auth contract.

The factor service itself does not require auth for read-only factor routes, but it extracts an incoming bearer token and forwards it to data-service. Supplying the same contributor JWT to factor therefore exercises the real factor→data auth propagation instead of bypassing it.

---

## 4. Factor probe request/response shapes match current schemas

Current `/catalog` returns factor entries containing:

```text
factor_id
source
available
...
```

So the macro probes' selection rule:

```text
source == "macro"
available == true
```

matches the live `CatalogResponse` shape.

Current `/score` accepts the exact fields used by the probes:

```text
venue
symbol
timeframe
lookback_bars
horizon_bars
quantiles
factor_ids
```

and returns:

```text
bars_used
factors
```

which are the fields collected by the contributor tooling.

The probes intentionally use explicit macro `factor_ids` when isolating macro fan-out. This still causes the normal main-price dataframe fetch because `_score_with_series()` always obtains the instrument bars needed to score the requested factors.

---

## 5. Runner preset timeframes are supported

The runner-like workload uses `1h` for:

```text
binance
baostock
yfinance
```

Current backfill routing supports that combination:

- Baostock explicitly supports `1h` and caps minute-level lookback to 60 days;
- yfinance supports `1h` with a recent-history window;
- Binance supports `1h` through its connector timeframe table.

The simulated live-runner lookback is only:

```text
max(5 × timeframe, 7200s)
```

so the fake workload does not intentionally trip Baostock/yfinance long-lookback restrictions.

This validates the preset as a control-flow reproduction rather than a collection of requests that would fail validation before reaching the provider phase.

---

## 6. Fake provider batch size is necessary and now enforced

`/backfill/bars` fetches in batches up to 1000 rows and advances the cursor from the final returned timestamp.

A fake connector returning one row for a long factor window would cause hundreds of artificial provider loops and benchmark the fake implementation instead of #107.

For factor/runner/mixed workloads we therefore require:

```text
ISSUE107_FAKE_BARS_PER_FETCH=1000
```

The runner/mixed preparation has been tightened so low fake batch counts are rejected rather than silently inflating provider-call counts.

---

## 7. Shared environment/JWT loading is compatible with service-local tools

`inalpha_shared.Settings` loads configuration from:

```text
<repo-root>/.env
then
./.env
```

with environment variables taking precedence.

That means probes materialized under `services/factor/` can use the same root `JWT_SECRET` as the running factor/data services without duplicating secrets into contributor files.

For the benchmark database we still explicitly export:

```text
DATABASE_URL=.../inalpha_issue107
```

so there is no ambiguity about which database receives/reset bars.

---

## 8. Preflight helper issue found and corrected

The PowerShell materialization helper previously ended by telling the contributor to read:

```text
.faysk-notes/11-local-test-runbook.md
```

as though that file existed in the working tree on `fix/data-service-saturation`.

It does not: the notes intentionally stay on `notes/issue-107`.

The helper now prints the correct non-merge command:

```powershell
git show origin/notes/issue-107:.faysk-notes/11-local-test-runbook.md
```

and its cleanup command references the actual temporary helper path.

This is exactly the kind of clerical issue the static readiness pass is meant to catch before runtime.

### Load-probe provider-safety guard

A more important tooling issue was found in the generic `issue107_load_probe.py`: unlike the macro/runner/mixed probes, it originally treated an unavailable contributor state endpoint as an empty observation and could still proceed with Binance backfills.

That meant a wrong `--base-url` could accidentally point the capacity probe at the ordinary data-service and hit a real provider.

The probe now fails closed **before creating any load** unless:

```text
GET /__issue107/state succeeds
AND
fake_venues includes binance
```

This makes the safety rule executable rather than depending on the contributor remembering the right target.

The timeout-persistence probe was already fail-closed because it requires the contributor state endpoint before sending timed backfills; factor/runner/mixed probes likewise validate the required fake venues.

---

## 9. Candidate A correctness guard: overlapping same-key writes

Current persistence uses unconditional:

```sql
ON CONFLICT (...) DO UPDATE
```

for OHLCV rows.

So concurrent same-key backfills can already do:

```text
request A reads same latest timestamp
request B reads same latest timestamp
A and B fetch overlapping provider windows
whichever DB write completes last wins for duplicate candles
```

This is an existing concurrency class, not a new Candidate A bug.

But Candidate A can let more provider work coexist because DB capacity is no longer the accidental admission limit. Therefore if H4/same-key duplication is material in runtime results, the before/after review must check that we did not turn a rare overlapping-write condition into a common one.

The latest candle deserves particular attention because the route intentionally re-fetches it to replace a previously forming candle.

Decision remains evidence-driven:

```text
same-key duplication immaterial
→ keep PR1 focused

same-key duplication material / final-candle completion inversion observed
→ add a focused correctness diagnostic before shipping
→ evaluate coalescing/admission only then
```

Do not preemptively add generic single-flight.

---

## 10. Two-worker Baostock caveat

Current repository production topology uses two data workers, but the Baostock connector source contains an explicit caution around its persistent Baostock login/session state and says that path is not fork-safe, recommending one worker or non-preloaded worker startup.

Separately, its A-share K-line path is protected by a process-local async source lock and timeout logic.

Our fake two-worker benchmark deliberately replaces `baostock` with a local fake. Therefore it is valid for measuring **data-service pool/request capacity under two workers**, but it cannot prove real Baostock session/fork correctness under that topology.

Do not write a PR claim such as:

```text
A-share provider behavior is proven safe with 2 workers
```

from fake-provider results.

If the representative #107 result depends materially on the real A-share path, do a low-volume connector verification or ask the maintainer about the actual deployment/process start model. Keep that separate from load testing so we do not stress public data sources.

---

## 11. What is now runtime-ready

Static compatibility has been checked for:

```text
branch/SHA preflight
pytest async/marker behavior
real app lifespan + registry fake injection
auth token shape
factor catalog/score schema fields
runner venue/timeframe presets
fake provider batch semantics
root/service environment loading
benchmark DB isolation
load probes fail closed unless required providers are fake
```

The remaining uncertainty is the uncertainty we actually want runtime to answer:

```text
H1   does provider wait materially starve DB capacity?
H1b  does that wait cross caller deadlines and become DATA_SERVICE_UNREACHABLE?
H6   does runner alignment materially amplify pressure?
H8   is macro same-key cold duplication material end-to-end?
H9   does timed-out client work survive long enough to overlap retries?
H10  does thread-backed provider work become a first constraint?
H11  is whole-score cold stampede material end-to-end?
H4   is cross-service/same-key duplicate backfill material enough to affect correctness/capacity?
```

That is the correct point to stop static speculation and start executing the prepared baseline.
