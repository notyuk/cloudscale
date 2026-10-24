// Mirrors the backend result schema (schema_version 1.0).

export type WorkloadPattern = "constant" | "poisson" | "sinusoidal" | "spike" | "ramp" | "bursty";

export type Workload =
  | { pattern: "constant"; rate: number }
  | { pattern: "poisson"; rate: number }
  | {
      pattern: "sinusoidal";
      base_rate: number;
      amplitude: number;
      period_s: number;
      phase_rad: number;
    }
  | {
      pattern: "spike";
      base_rate: number;
      spike_rate: number;
      spike_start_s: number;
      spike_duration_s: number;
    }
  | { pattern: "ramp"; start_rate: number; end_rate: number }
  | {
      pattern: "bursty";
      base_rate: number;
      peak_multiplier: number;
      mean_burst_s: number;
      mean_gap_s: number;
    };

export interface ServiceTime {
  distribution: "constant" | "exponential" | "lognormal";
  mean_work: number;
  cv: number;
}

export interface Cluster {
  slots_per_server: number;
  server_speed: number;
  min_replicas: number;
  max_replicas: number;
  initial_replicas: number;
  provisioning_delay_s: number;
  max_pending: number;
}

export interface Scenario {
  duration_s: number;
  seed: number;
  workload: Workload;
  service: ServiceTime;
  cluster: Cluster;
  sla: { latency_threshold_s: number; penalty_per_violation: number };
  cost: { server_price_per_hour: number };
  control_interval_s: number;
  metrics_interval_s: number;
}

export interface FixedStrategy {
  type: "fixed";
  label?: string | null;
  replicas: number;
}

export interface ReactiveStrategy {
  type: "reactive";
  label?: string | null;
  upper_threshold: number;
  lower_threshold: number;
  target_utilisation: number;
  observation_window_s: number;
  scale_up_cooldown_s: number;
  scale_down_cooldown_s: number;
  max_step_up: number;
  max_step_down: number;
  backlog_drain_s: number;
}

export interface PredictiveStrategy {
  type: "predictive";
  label?: string | null;
  alpha: number;
  beta: number;
  horizon_s: number | null;
  target_utilisation: number;
  lower_threshold: number;
  scale_up_cooldown_s: number;
  scale_down_cooldown_s: number;
  max_step_up: number;
  max_step_down: number;
  warmup_intervals: number;
  reactive_floor: boolean;
  backlog_drain_s: number;
}

export type Strategy = FixedStrategy | ReactiveStrategy | PredictiveStrategy;
export type StrategyType = Strategy["type"];

export interface LatencyStats {
  mean_s: number | null;
  median_s: number | null;
  p95_s: number | null;
  p99_s: number | null;
  max_s: number | null;
}

export interface Summary {
  requests_total: number;
  requests_completed: number;
  requests_rejected: number;
  requests_unfinished: number;
  requests_unfinished_queued: number;
  requests_unfinished_in_service: number;
  throughput_rps: number;
  latency: LatencyStats;
  latency_p95_lower_bound_s: number | null;
  latency_p99_lower_bound_s: number | null;
  mean_wait_s: number | null;
  max_wait_s: number | null;
  queue_length_mean: number;
  queue_length_peak: number;
  utilisation_mean: number | null;
  paid_utilisation_mean: number | null;
  replicas_mean: number;
  replicas_peak: number;
  scale_up_events: number;
  scale_down_events: number;
  servers_launched: number;
  launches_cancelled: number;
  provisioning_delay_mean_s: number | null;
  server_hours: number;
  compute_cost: number;
  sla_penalty_cost: number;
  total_cost: number;
  cost_per_completed_request: number | null;
  sla_threshold_s: number;
  sla_violations: number;
  sla_undetermined: number;
  sla_violation_pct: number | null;
}

export interface TimeSeries {
  t_start: number[];
  t_end: number[];
  arrivals: number[];
  arrival_rate_rps: number[];
  completions: number[];
  rejections: number[];
  sla_violations: number[];
  latency_mean_s: (number | null)[];
  latency_p95_s: (number | null)[];
  queue_length_mean: number[];
  queue_length_end: number[];
  active_end: number[];
  starting_end: number[];
  draining_end: number[];
  replicas_mean: number[];
  utilisation: (number | null)[];
  capacity_rps: number[];
  busy_slot_seconds: number[];
  capacity_slot_seconds: number[];
  paid_server_seconds: number[];
  cost: number[];
  cost_cumulative: number[];
}

export interface ScalingEvent {
  time_s: number;
  from_replicas: number;
  to_replicas: number;
  reason: string;
  launched: number;
  reactivated: number;
  cancelled: number;
  terminated: number;
  drained: number;
}

export interface SimulationResult {
  schema_version: string;
  strategy: { label: string; config: Strategy };
  summary: Summary;
  timeseries: TimeSeries;
  scaling_events: ScalingEvent[];
  latency_histogram: { bin_edges: number[]; counts: number[] };
  runtime: { wall_time_ms: number; events_processed: number };
}

export interface ComparisonResult {
  schema_version: string;
  scenario: Scenario;
  requests_generated: number;
  results: SimulationResult[];
}

export interface Defaults {
  scenario: Scenario;
  strategies: Strategy[];
  workload_patterns: WorkloadPattern[];
  limits: {
    max_expected_requests_per_run: number;
    max_total_expected_requests: number;
    max_compare_strategies: number;
    max_body_bytes: number;
    wall_time_budget_s: number | null;
  };
}

export interface ApiErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}
