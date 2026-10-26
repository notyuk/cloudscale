# ADR 0001: Discrete-event simulation instead of fixed time steps

**Status:** accepted

## Context

The simulator has to measure per-request latency down to milliseconds, reproduce
results exactly, and handle runs with hundreds of thousands of requests in a few
seconds of CPU time.

## Options

1. **Fixed time step** (advance the clock by `dt`, process everything due). Simple, but
   latency resolution is limited to `dt`. A small `dt` wastes work on idle periods, and
   ordering within a step is arbitrary unless it is carefully specified.
2. **Discrete-event simulation (DES)** with a priority queue. The clock jumps from one
   event to the next. Resolution is exact, and the cost scales with the number of
   events rather than with simulated time.
3. **Analytical queueing models** (M/M/c, Erlang C). Fast, but they assume
   steady-state Poisson traffic and can't represent provisioning delays, cooldowns or
   time-varying load.
4. **An existing DES library** (SimPy). Mature, but its coroutine model hides the event
   ordering, so tie-breaking is harder to specify and test. It also adds overhead per
   event.

## Decision

Implement a small purpose-built DES on top of `heapq`. Events are ordered by
`(time, kind priority, insertion sequence)`, which gives an explicit, documented and
tested rule for simultaneous events. Arrivals come from a pre-sorted NumPy array and
are merged with the heap instead of being pushed onto it.

## Consequences

* Exact latencies and fully deterministic runs, verified by property tests.
* The tie-breaking rules (completion before arrival before control) are part of the
  model and are documented in `docs/simulation-model.md`.
* Pure-Python event processing costs about 1.3 µs per event (~370k requests/s on a
  laptop for a 1 h, 60 req/s run), so the API caps runs at 1M expected requests. If
  this became a bottleneck, the event loop is small enough to port to Rust or Cython
  without changing its interface.
