# ADR 0003: Stateless synchronous API with schemas shared with the core

**Status:** accepted

## Context

The frontend needs to run single simulations and comparisons. Runs take between a few
milliseconds and roughly ten seconds of CPU time.

## Options

1. **Job queue** (Celery/RQ + Redis, poll for results). Handles long jobs and survives
   restarts, but adds two services, persistence and a polling protocol for jobs that
   usually finish in under a few seconds.
2. **Synchronous request/response** with strict cost limits. One process, no storage,
   trivially horizontally scalable, and results can be reproduced from the request
   alone because runs are deterministic.
3. **WebSocket streaming** of progress. Nicer for very long runs, but it complicates
   the client and the tests for little benefit at the current run sizes.

For validation schemas: either separate API DTOs mapped onto core dataclasses, or the
same Pydantic models used by the core, the API and the experiment suite.

## Decision

* Synchronous REST endpoints. They are `def` (not `async def`) handlers, so FastAPI
  runs these CPU-bound calls in its thread pool. A bounded semaphore caps concurrent
  simulations (503 + `Retry-After` when saturated).
* Cost control in three layers: request body size (413); an *expected* request count
  computed analytically from the rate function before any trace is generated (422);
  and a wall-clock budget checked inside the event loop (422).
* Configuration models are Pydantic v2 models that live in the core packages
  (`workloads/config.py`, `strategies/config.py`, `simulation/config.py`). The API
  reuses them directly. Pydantic is a validation library, not a web framework, so the
  core still has no FastAPI/HTTP dependency (an AST-based test enforces this).
* Results carry `schema_version`, and the time series include raw integrals so clients
  can recompute every derived value.

## Consequences

* No database, queue or session state. A request plus its seed fully determines the
  response.
* One definition of every validation rule, shared by API, experiments and tests.
* Long-running studies (e.g. 24 h at high rates) belong in the offline experiment
  runner, not the API. If interactive long runs were needed, adding a job queue would
  be the next step.
