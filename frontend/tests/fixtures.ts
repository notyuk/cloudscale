import type { Scenario, SimulationResult, Summary, TimeSeries } from "@/lib/types";

export const scenario: Scenario = {
  duration_s: 3600,
  seed: 42,
  workload: { pattern: "sinusoidal", base_rate: 20, amplitude: 15, period_s: 600, phase_rad: 0 },
  service: { distribution: "exponential", mean_work: 0.2, cv: 1 },
  cluster: {
    slots_per_server: 4,
    server_speed: 1,
    min_replicas: 1,
    max_replicas: 20,
    initial_replicas: 2,
    provisioning_delay_s: 60,
    max_pending: 10000,
  },
  sla: { latency_threshold_s: 1, penalty_per_violation: 0 },
  cost: { server_price_per_hour: 0.1 },
  control_interval_s: 15,
  metrics_interval_s: 15,
};

export function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    requests_total: 100,
    requests_completed: 98,
    requests_rejected: 0,
    requests_unfinished: 2,
    requests_unfinished_queued: 1,
    requests_unfinished_in_service: 1,
    throughput_rps: 1.5,
    latency: { mean_s: 0.3, median_s: 0.2, p95_s: 0.9, p99_s: 1.4, max_s: 2 },
    latency_p95_lower_bound_s: 0.95,
    latency_p99_lower_bound_s: 1.5,
    mean_wait_s: 0.1,
    max_wait_s: 1,
    queue_length_mean: 0.4,
    queue_length_peak: 7,
    utilisation_mean: 0.55,
    paid_utilisation_mean: 0.5,
    replicas_mean: 3,
    replicas_peak: 5,
    scale_up_events: 2,
    scale_down_events: 1,
    servers_launched: 3,
    launches_cancelled: 0,
    provisioning_delay_mean_s: 60,
    server_hours: 3,
    compute_cost: 0.3,
    sla_penalty_cost: 0,
    total_cost: 0.3,
    cost_per_completed_request: 0.003,
    sla_threshold_s: 1,
    sla_violations: 3,
    sla_undetermined: 1,
    sla_violation_pct: 3.03,
    ...overrides,
  };
}

export function timeseries(n = 3): TimeSeries {
  const range = (f: (i: number) => number) => Array.from({ length: n }, (_, i) => f(i));
  return {
    t_start: range((i) => i * 60),
    t_end: range((i) => (i + 1) * 60),
    arrivals: range((i) => 10 + i),
    arrival_rate_rps: range((i) => (10 + i) / 60),
    completions: range(() => 10),
    rejections: range(() => 0),
    sla_violations: range(() => 1),
    latency_mean_s: range((i) => (i === 1 ? NaN : 0.2)).map((v) => (Number.isNaN(v) ? null : v)),
    latency_p95_s: range(() => 0.5),
    queue_length_mean: range(() => 0),
    queue_length_end: range(() => 0),
    active_end: range(() => 2),
    starting_end: range(() => 0),
    draining_end: range(() => 0),
    replicas_mean: range(() => 2),
    utilisation: range(() => 0.5),
    capacity_rps: range(() => 40),
    busy_slot_seconds: range(() => 240),
    capacity_slot_seconds: range(() => 480),
    paid_server_seconds: range(() => 120),
    cost: range(() => 0.01),
    cost_cumulative: range((i) => 0.01 * (i + 1)),
  };
}

export function result(label: string, overrides: Partial<Summary> = {}): SimulationResult {
  return {
    schema_version: "1.0",
    strategy: { label, config: { type: "fixed", replicas: 3 } },
    summary: summary(overrides),
    timeseries: timeseries(),
    scaling_events: [],
    latency_histogram: { bin_edges: [0, 1, 2], counts: [90, 8] },
    runtime: { wall_time_ms: 10, events_processed: 300 },
  };
}
