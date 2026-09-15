# Issue #107 — Solution Design

**Status:** intentionally blank until baseline evidence exists.

This document records the implementation we actually choose after reproducing #107.

---

## 1. Evidence that justifies this design

```text
Baseline commit:
Reproduction scenario:
Observed bottleneck:
Measured evidence:
Why this is the smallest useful intervention:
```

---

## 2. Chosen design

```text
TBD after baseline
```

### Intended behavior

```text
request
→ validation
→ capacity/backpressure behavior
→ expensive operation
→ persistence/read
→ response
```

---

## 3. Configuration

New/changed settings, if any:

| Setting | Default | Meaning | Why needed |
|---|---:|---|---|
| TBD | TBD | TBD | TBD |

Rules:

- safe default,
- environment-configurable where appropriate,
- no unexplained magic values,
- concurrency value justified by benchmark.

---

## 4. Error semantics

Document any new/changed error:

```json
{
  "code": "TBD",
  "message": "TBD",
  "details": {}
}
```

Questions:

- Is it retryable?
- Which HTTP status is appropriate?
- Which callers consume it?
- Can a caller silently fall back to stale data?
- Does the response preserve current/fresh semantics?

---

## 5. Concurrency semantics

```text
Global limit:
Per-provider limit:
Queue/wait policy:
Timeout:
Cancellation behavior:
Slot release guarantees:
Multi-worker behavior:
```

If process-local only, say that explicitly.

---

## 6. Observability

Fields/events to add:

```text
TBD
```

Prefer existing `structlog` + trace infrastructure in the first PR.

---

## 7. Files to change

```text
TBD
```

For every file, state why it needs to change.

Avoid touching `services/_shared/` unless agreed with maintainer.

---

## 8. Tests

Required deterministic tests:

- [ ] capacity never exceeds configured limit
- [ ] success releases capacity
- [ ] exception releases capacity
- [ ] cancellation releases capacity
- [ ] wait/timeout semantics correct
- [ ] upstream error semantics preserved
- [ ] auth remains isolated
- [ ] freshness behavior preserved
- [ ] same-key behavior if single-flight is included

---

## 9. Rejected alternatives

For each alternative record why it was not chosen.

### Increase Uvicorn workers

```text
Decision: TBD
Reason: TBD
```

### Lower factor panel concurrency only

```text
Decision: TBD
Reason: current panel already bounded; measurement required.
```

### Per-provider semaphores immediately

```text
Decision: defer unless provider starvation is measured.
```

### Distributed queue / Redis lock

```text
Decision: defer unless process-local coordination is proven insufficient.
```

### More client retries

```text
Decision: avoid as primary sustained-overload solution; may amplify load.
```

---

## 10. Rollback

```text
How to disable/revert the behavior:
Config rollback:
Code rollback:
Any data migration involved? ideally no for PR 1.
```

---

## 11. Maintainer alignment

```text
Date:
Maintainer feedback:
Scope agreed:
Open questions:
```
