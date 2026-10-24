# Simulation model

This is the precise definition of what the simulator does. The engine
(`backend/app/simulation/engine.py`) and the property tests
(`backend/tests/test_properties.py`) follow this document.

## Units

| Quantity | Unit |
|---|---|
| Time | seconds of simulated time (logical clock, float64) |
| Arrival rate | requests per second |
| Work | work units; 1 unit takes 1 s on one slot of a server with `server_speed = 1` |
| Price | currency per server-hour |
| Capacity | slots (concurrent requests) |

## Workload

A trace is two arrays: sorted arrival times `a_i ∈ [0, T)` and work `w_i > 0`.
Both are generated from one `numpy.random.SeedSequence(seed)` that is split into two
independent child streams. Changing the work distribution therefore never moves the
arrival times. No global random state is used.

| Pattern | λ(t) | Process |
|---|---|---|
| `constant` | `r` | deterministic, gaps of `1/r`, first arrival at `1/(2r)` |
| `poisson` | `r` | homogeneous Poisson: `N ~ Poisson(rT)`, times are sorted uniforms |
| `sinusoidal` | `b + A·sin(2πt/P + φ)`, `A ≤ b` | non-homogeneous Poisson via thinning |
| `spike` | `b`, or `s` for `t ∈ [t0, t0+d)` | thinning |
| `ramp` | `r0 + (r1 − r0)·t/T` | thinning |
| `bursty` | 2-state MMPP: `b` or `b·m`; exponential sojourns with means `gap`, `burst` | piecewise homogeneous Poisson; starts in the normal state |

Thinning (Lewis–Shedler): draw a homogeneous process at `λmax`, keep each candidate
with probability `λ(t)/λmax`.

Work: `constant`, `exponential(mean)` or `lognormal` parameterised so that `E[w] = mean`
and `SD[w]/E[w] = cv` (`σ² = ln(1 + cv²)`, `μ = ln(mean) − σ²/2`).

## Servers and service discipline

* There is one global FIFO queue in front of the server pool, like an idealised load
  balancer queue. It holds at most `max_pending` requests.
* Each server has `slots_per_server` independent slots, and each slot processes one
  request at a time. Request `i` occupies a slot for `w_i / server_speed` seconds.
  There is no processor sharing and no preemption.
* Dispatch is work-conserving. Whenever a slot is free and the queue is not empty, the
  head of the queue starts on the lowest-numbered `ACTIVE` server with a free slot
  (bin packing). Packing leaves high-numbered servers idle so they can be removed
  without draining.
* Capacity is never exceeded. After every event (in tests), the engine checks
  `in_flight ≤ slots` for every server and that the queue is empty whenever any active
  slot is free.

### Server lifecycle

```
STARTING ──ready──▶ ACTIVE ──scale down (busy)──▶ DRAINING ──last request done──▶ TERMINATED
   │                  │  ▲                            │
   │                  │  └──────scale up (reuse)──────┘
   │                  └──scale down (idle)───────────────────────────────────────▶ TERMINATED
   └──scale down (cancel)────────────────────────────────────────────────────────▶ TERMINATED
```

* A launched server becomes `ACTIVE` exactly `provisioning_delay_s` after launch.
* `initial_replicas` servers are `ACTIVE` at `t = 0` with no delay. The fixed strategy
  starts with its own replica count instead, so the baseline is not penalised by a
  cold start.
* Only `ACTIVE` servers receive work. `DRAINING` servers finish their in-flight
  requests and then terminate.
* Billing runs while a server is `STARTING`, `ACTIVE` or `DRAINING`.

### Request lifecycle

```
PENDING ──arrive──▶ QUEUED ──dispatch──▶ IN_SERVICE ──finish──▶ COMPLETED
   │                  │                     │
   └──queue full──▶ REJECTED               └──t = T──▶ UNFINISHED
                      └──────────t = T──────────────▶ UNFINISHED
```

Every request ends in exactly one of `COMPLETED`, `REJECTED` or `UNFINISHED`. No
request is ever dropped silently. Illegal transitions raise `InvalidTransitionError`.
A request that arrives when the queue already holds `max_pending` requests and no slot
is free is `REJECTED`. With `max_pending = 0` a request is still served if a slot is
free.

## Events and ordering

The simulation covers the half-open interval `[0, T)`. Events at or after `T` are not
processed. A completion scheduled at exactly `T` leaves its request `UNFINISHED`.

Events are ordered by `(time, kind priority, insertion sequence)`:

| Priority | Event | Why this order |
|---|---|---|
| 0 | `SAMPLE` (metrics bucket boundary) | a bucket closes before anything at its boundary |
| 1 | `COMPLETION` | freed slots are visible to arrivals at the same instant |
| 2 | `SERVER_READY` | new capacity is visible to arrivals at the same instant |
| 3 | `ARRIVAL` | |
| 4 | `CONTROL` (autoscaler tick) | the controller sees every arrival up to and including its tick |

The insertion sequence makes ties within a kind FIFO, so runs are fully deterministic.
Arrivals are not pushed onto the heap. They are merged from the pre-sorted array,
which roughly halves heap traffic.

**Complexity.** Each request causes one arrival, at most one dispatch and one
completion, so a run costs `O((N + E) log H)`, where `H` (the heap size) is bounded by
in-flight requests plus pending timers. Memory is `O(N)`. Scaling actions sort the
live servers, `O(S log S)`, but they only happen once per control interval.

## Scaling

Every `control_interval_s` the strategy receives an `Observation` and returns a desired
number of *committed* replicas (`ACTIVE + STARTING`). The engine clamps it to
`[min_replicas, max_replicas]` and then applies it:

* **Scale up:** first reactivate `DRAINING` servers (they are warm and already paid
  for), then launch new ones.
* **Scale down:** first cancel `STARTING` servers (newest first), then remove `ACTIVE`
  servers in order of fewest in-flight requests (newest first on ties). Idle ones
  terminate immediately; busy ones drain.

Cooldowns, hysteresis and step limits belong to the strategies. Bounds and
provisioning delays belong to the engine, so a faulty strategy cannot break physical
constraints.

### Observation (no future data)

The observation contains the current time and interval length, the current counts of
active/starting/draining servers, the queue length and busy slots, the static cluster
parameters, and these aggregates over `(t − Δ, t]`: arrivals, completions, rejections,
busy slot-seconds and serving slot-seconds. It also includes an EWMA (α = 0.3, per
interval) of the observed service durations of *completed* requests.

All of these are computed from events that have already happened. Strategies never get
a reference to the trace or the event queue. `test_no_future_data_leakage` builds two
traces that are identical before `t = 1500 s` and very different afterwards, and checks
that every decision up to 1500 s is identical.

## Strategies

**Fixed.** `desired = replicas`.

**Reactive.** Over the observation window `W`:

* `U = Σ busy slot-seconds / Σ serving slot-seconds`
* `B̄ = Σ busy slot-seconds / W` (mean busy slots)
* `backlog = queue · ŝ / backlog_drain_s` (slots needed to clear the queue in time; `ŝ` is the service-time estimate)
* `needed = ⌈(B̄ + backlog) / (target · slots_per_server)⌉`

| Condition | Action |
|---|---|
| `U > upper` and scale-up cooldown has passed and `needed > committed` | `min(needed, committed + max_step_up, max)` |
| `U < lower`, queue empty, nothing booting, scale-down cooldown passed | `max(needed, committed − max_step_down, min)` |
| otherwise | hold |

The band `[lower, upper]` is the hysteresis. Cooldowns are measured from the last
scaling action in either direction.

**Predictive.** Holt's linear trend method on the per-interval arrival rate `r_t`:

```
level_t = α r_t + (1 − α)(level_{t−1} + trend_{t−1})
trend_t = β (level_t − level_{t−1}) + (1 − β) trend_{t−1}
forecast(h) = max(0, level_t + trend_t · h/Δ)
```

with `h = provisioning_delay_s + control_interval_s` by default. Demand in slots
follows Little's law: `forecast · ŝ`. Then
`needed = ⌈(forecast·ŝ + backlog) / (target · slots)⌉`. With `reactive_floor` the
controller never goes below what the current interval's demand
`max(B, r_t·ŝ)` needs. It scales down only when the projected utilisation of the
current fleet drops below `lower_threshold`. During warm-up it uses the reactive
(current-demand) sizing.

## Metrics

Let `C` be the completed requests, `U` the unfinished requests, `R` the rejected
requests, and `L_i = completion_i − arrival_i`.

| Metric | Definition |
|---|---|
| Latency mean / median / P95 / P99 / max | over `{L_i : i ∈ C}`, NumPy linear-interpolation percentiles |
| P95 / P99 lower bound | percentile over `{L_i : i ∈ C} ∪ {T − a_i : i ∈ U}`. Unfinished requests have waited *at least* their age, so this is a lower bound on the true percentile when there is a backlog |
| Throughput | `|C| / T` |
| Mean wait | `start − arrival` over requests that started |
| Max wait | includes requests still waiting at `T` (`T − a_i`) |
| Queue length mean | `∫ q(t) dt / T` (time-weighted, not per-event) |
| Utilisation | `∫ busy slots dt / ∫ serving slots dt`, where serving = all slots of `ACTIVE` servers + occupied `DRAINING` slots |
| Paid utilisation | `∫ busy slots dt / (slots · ∫ billed servers dt)` |
| Mean replicas | `∫ billed servers dt / T` |
| Peak replicas | maximum number of simultaneously billed servers (sweep over server lifetimes) |
| Server hours | `∫ billed servers dt / 3600` |
| Compute cost | `server hours × price` |
| SLA violations | `|{i ∈ C : L_i > θ}| + |{i ∈ U : T − a_i > θ}| + |R|` |
| SLA undetermined | `|{i ∈ U : T − a_i ≤ θ}|`. These may still meet the SLA, so they are excluded |
| SLA violation % | `violations / (N − undetermined)` |
| Total cost | `compute cost + violations × penalty` |
| Cost per completed request | `compute cost / |C|`, or `null` if `|C| = 0` |

Any metric over an empty population is `null`, never `0` or `NaN`.

Time series use buckets of `metrics_interval_s` over `[k·Δ, (k+1)·Δ)`. The last bucket
may be shorter. Arrivals and rejections are bucketed by arrival time, completions and
latency by completion time. Each bucket also includes the raw integrals (busy/capacity
slot-seconds, billed server-seconds), so every derived series can be recomputed from
the response. `test_timeseries_buckets_reconcile_with_summary` checks that the buckets
add up to the summary.

## Limitations

* There is a single queue and identical servers. There is no per-server queueing,
  routing imbalance or heterogeneous instance types.
* There is no network latency, no request timeout or retry, and no failures.
* The provisioning delay is constant. There is no jitter and no failed launches.
* Billing is continuous (per second), with no minimum billing increment.
* Strategies observe exact counters with no metric-pipeline lag beyond the control
  interval.
* The simulator is single-threaded Python, about 1.3 µs per event on a laptop. The API
  limits a run to 1M expected requests (2.5M across a comparison).
