# ADR 0002: Strategies see a past-only Observation; the engine enforces constraints

**Status:** accepted

## Context

Comparing autoscalers is only meaningful if no strategy can peek at future load, and if
every strategy is held to the same physical limits (replica bounds, boot time). A
predictive strategy that could read the trace would look unrealistically good.

## Options

1. **Pass the engine (or trace) to the strategy** and trust each strategy to look only
   at the past. Flexible, but nothing enforces it, so leakage is easy to introduce by
   accident.
2. **Give strategies a read-only snapshot of past aggregates** (an immutable
   `Observation`), and have the engine apply the decision. Leakage is impossible by
   construction.
3. **Run strategies in a separate process** with an RPC boundary. Strong isolation, but
   heavy for a simulator that calls the controller every 15 simulated seconds.

## Decision

Option 2. `Observation` is a frozen dataclass built from counters that the engine
updates as events are processed. It covers only the interval that just ended plus
the instantaneous state. Strategies return a desired committed replica count. The
engine clamps it to `[min_replicas, max_replicas]` and applies provisioning delays,
cancellation and draining.

Cooldowns, hysteresis and step limits stay inside strategies, because they are policy,
not physics.

## Consequences

* `test_no_future_data_leakage` runs each adaptive strategy on two traces that share
  their first half and diverge afterwards. It asserts that every decision in the first
  half is identical.
* A buggy or adversarial strategy can't exceed replica bounds or skip boot time. The
  invariant checker verifies this after every event in the property tests.
* Strategies that need history (windows, forecasts) keep it themselves, which keeps the
  engine simple and makes strategies independently unit-testable with hand-built
  observations.
