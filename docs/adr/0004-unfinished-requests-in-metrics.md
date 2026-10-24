# ADR 0004: How unfinished and rejected requests enter the metrics

**Status:** accepted

## Context

When a strategy under-provisions, a backlog builds up and many requests are still
queued when the simulation ends. Latency percentiles computed only over completed
requests then look *better* the worse the backlog is, because the slowest requests
never complete.

## Options

1. Report percentiles over completed requests only. This is standard but misleading
   under overload.
2. Keep running the simulation after `T` until the queue drains. The latency becomes
   exact, but cost and capacity after `T` are no longer comparable across strategies,
   and a permanently overloaded system never drains.
3. Treat unfinished requests as censored observations. Report their count, use their
   elapsed age as a lower bound, and count them as SLA violations once that age exceeds
   the threshold.

## Decision

Option 3:

* `latency.*` covers completed requests only. The summary always shows
  `requests_unfinished` (split into queued / in service) next to it.
* `latency_p95_lower_bound_s` and `latency_p99_lower_bound_s` include unfinished
  requests at age `T − arrival`. This is a valid lower bound on the true percentile.
* An unfinished request older than the SLA threshold is a violation. A younger one is
  *undetermined* and excluded from the violation-rate denominator.
* Rejected requests (queue full) are always violations.

## Consequences

The dashboard and benchmark report show the backlog explicitly. The comparison view
adds a warning whenever more than 1% of requests are unfinished, so a strategy cannot
look fast by never finishing its slow requests.
