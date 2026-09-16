# Issue #107 — Sustained Child-Task Cancellation Guard

**Status:** contributor-harness correctness fix before runtime.  
**Production impact:** none.

---

## 1. Static issue found

The sustained acceptance cycle creates several independent asyncio tasks:

```text
factor requests
runner refresh/read requests
OpenAPI controls
health controls
```

In Python, arbitrary tasks created with `asyncio.create_task()` are not automatically owned/cancelled as a hierarchy merely because the parent coroutine is cancelled.

The earlier cycle implementation awaited the task groups sequentially:

```text
await factor tasks
await runner tasks
await openapi tasks
await health tasks
```

If the parent cycle was cancelled while awaiting the first group — for example because the benchmark settle timeout expired — sibling runner/control tasks that had already been created could continue running.

That would create exactly the kind of measurement bug we are trying to avoid:

```text
benchmark says pending cycles were cancelled
but
some child requests remain in flight
→ final provider/pool state includes orphan load
→ next run can start before old load drains
→ before/after evidence becomes contaminated
```

---

## 2. Acceptance probe fix

`issue107_sustained_acceptance_probe.py` now keeps an explicit list of every child task created by one cycle.

The cycle:

1. starts factor + runner tasks;
2. waits the configured control start delay;
3. creates OpenAPI + health controls;
4. awaits all child tasks as one result set;
5. in a `finally` block, cancels every unfinished child;
6. awaits all children with `return_exceptions=True` before the cycle task can finish.

Therefore when `_collect_finished()` cancels an unfinished cycle after the settle timeout, that cycle cannot return from cancellation while its explicitly spawned request tasks remain alive in the probe process.

---

## 3. Why this matters especially for H9

H9 asks whether **server/provider work** can outlive a client cancellation/deadline.

The load generator itself must not add a second unrelated ambiguity where its own local client tasks accidentally survive because the harness forgot to cancel them.

After this guard:

```text
client task was deliberately cancelled/drained
AND
server/provider counters remain active
```

is much stronger H9 evidence than:

```text
some local tasks might still be running; not sure
```

This does not guarantee a remote server stops work when the client task is cancelled. That is precisely what the real-TCP H9 experiment is designed to measure.

---

## 4. Final-state sampling rule

The acceptance probe cancels/drains pending cycle tasks before taking its final `after_state` sample.

So one-worker before/after provider/pool deltas are no longer knowingly sampled while orphan load-generator children remain alive.

For thread-backed provider mode, an already-running synchronous worker may still outlive cancellation; `thread_active` exists specifically to reveal that distinction.

---

## 5. Scope

This fix applies to the acceptance-oriented sustained probe used for O1/O2/O3 evidence.

The older `issue107_sustained_mixed_probe.py` is retained mainly as shared helper/base machinery and historical same-key soak code. Final sustained evidence must use:

```text
issue107_sustained_acceptance_probe.py
```

not the older base probe directly.

---

## Working-principle check

This was another example of the contribution rule:

> Resolve #107 without creating a second problem in the measurement system.

Before trusting a capacity result, we need confidence not only in the service under test, but also that the harness stops generating load when it says it has stopped.
