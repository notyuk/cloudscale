// Client-side checks for immediate feedback. The backend re-validates everything
// and its 422 response is shown as well, so these only need to cover common mistakes.
import type { Scenario, Strategy } from "./types";

export type Errors = Record<string, string>;

type Range = [path: string, value: number, min: number, max: number, exclusiveMin?: boolean];

function checkRanges(ranges: Range[], errors: Errors) {
  for (const [path, value, min, max, exclusiveMin] of ranges) {
    if (!Number.isFinite(value)) errors[path] = "Required";
    else if (exclusiveMin ? value <= min : value < min)
      errors[path] = exclusiveMin ? `Must be greater than ${min}` : `Must be at least ${min}`;
    else if (value > max) errors[path] = `Must be at most ${max}`;
  }
}

export function validateScenario(s: Scenario): Errors {
  const errors: Errors = {};
  const c = s.cluster;
  checkRanges(
    [
      ["duration_s", s.duration_s, 0, 86_400, true],
      ["seed", s.seed, 0, 2 ** 32 - 1],
      ["control_interval_s", s.control_interval_s, 0, 3_600, true],
      ["metrics_interval_s", s.metrics_interval_s, 0, 3_600, true],
      ["service.mean_work", s.service.mean_work, 0, 3_600, true],
      ["service.cv", s.service.cv, 0, 10, true],
      ["cluster.slots_per_server", c.slots_per_server, 1, 256],
      ["cluster.server_speed", c.server_speed, 0, 100, true],
      ["cluster.min_replicas", c.min_replicas, 1, 1_000],
      ["cluster.max_replicas", c.max_replicas, 1, 1_000],
      ["cluster.initial_replicas", c.initial_replicas, 1, 1_000],
      ["cluster.provisioning_delay_s", c.provisioning_delay_s, 0, 3_600],
      ["cluster.max_pending", c.max_pending, 0, 1_000_000],
      ["sla.latency_threshold_s", s.sla.latency_threshold_s, 0, 3_600, true],
      ["sla.penalty_per_violation", s.sla.penalty_per_violation, 0, 1_000],
      ["cost.server_price_per_hour", s.cost.server_price_per_hour, 0, 1_000],
    ],
    errors,
  );
  if (c.min_replicas > c.max_replicas) errors["cluster.max_replicas"] = "Must be ≥ min replicas";
  if (c.initial_replicas < c.min_replicas || c.initial_replicas > c.max_replicas)
    errors["cluster.initial_replicas"] = "Must be between min and max replicas";
  if (s.control_interval_s > s.duration_s)
    errors["control_interval_s"] = "Must not exceed the duration";
  if (s.duration_s / s.metrics_interval_s > 2_000)
    errors["metrics_interval_s"] = "Too many buckets (duration / interval > 2000)";

  const w = s.workload;
  const rate = (path: string, value: number) =>
    checkRanges([[`workload.${path}`, value, 0, 5_000, true]], errors);
  switch (w.pattern) {
    case "constant":
    case "poisson":
      rate("rate", w.rate);
      break;
    case "sinusoidal":
      rate("base_rate", w.base_rate);
      checkRanges(
        [
          ["workload.amplitude", w.amplitude, 0, 5_000],
          ["workload.period_s", w.period_s, 0, 1e9, true],
        ],
        errors,
      );
      if (w.amplitude > w.base_rate) errors["workload.amplitude"] = "Must not exceed base rate";
      break;
    case "spike":
      rate("base_rate", w.base_rate);
      rate("spike_rate", w.spike_rate);
      checkRanges(
        [
          ["workload.spike_start_s", w.spike_start_s, 0, 1e9],
          ["workload.spike_duration_s", w.spike_duration_s, 0, 1e9, true],
        ],
        errors,
      );
      if (w.spike_rate <= w.base_rate) errors["workload.spike_rate"] = "Must exceed base rate";
      if (w.spike_start_s >= s.duration_s)
        errors["workload.spike_start_s"] = "Must start before the run ends";
      break;
    case "ramp":
      rate("start_rate", w.start_rate);
      rate("end_rate", w.end_rate);
      break;
    case "bursty":
      rate("base_rate", w.base_rate);
      checkRanges(
        [
          ["workload.peak_multiplier", w.peak_multiplier, 1, 100, true],
          ["workload.mean_burst_s", w.mean_burst_s, 0, 1e9, true],
          ["workload.mean_gap_s", w.mean_gap_s, 0, 1e9, true],
        ],
        errors,
      );
      break;
  }
  return errors;
}

export function validateStrategy(st: Strategy, s: Scenario): Errors {
  const errors: Errors = {};
  if (st.type === "fixed") {
    checkRanges([["replicas", st.replicas, 1, 1_000]], errors);
    if (st.replicas < s.cluster.min_replicas || st.replicas > s.cluster.max_replicas)
      errors.replicas = `Must be within ${s.cluster.min_replicas}–${s.cluster.max_replicas}`;
    return errors;
  }
  checkRanges(
    [
      ["target_utilisation", st.target_utilisation, 0, 1, true],
      ["lower_threshold", st.lower_threshold, 0, 1],
      ["scale_up_cooldown_s", st.scale_up_cooldown_s, 0, 3_600],
      ["scale_down_cooldown_s", st.scale_down_cooldown_s, 0, 7_200],
      ["max_step_up", st.max_step_up, 1, 1_000],
      ["max_step_down", st.max_step_down, 1, 1_000],
    ],
    errors,
  );
  if (st.type === "reactive") {
    checkRanges(
      [
        ["upper_threshold", st.upper_threshold, 0, 1, true],
        ["observation_window_s", st.observation_window_s, 0, 3_600, true],
      ],
      errors,
    );
    if (!(st.lower_threshold < st.target_utilisation && st.target_utilisation < st.upper_threshold))
      errors.target_utilisation = "Need lower < target < upper";
  } else {
    checkRanges(
      [
        ["alpha", st.alpha, 0, 1, true],
        ["beta", st.beta, 0, 1],
        ["warmup_intervals", st.warmup_intervals, 0, 1_000],
      ],
      errors,
    );
    if (st.horizon_s !== null) checkRanges([["horizon_s", st.horizon_s, 0, 3_600, true]], errors);
    if (st.lower_threshold >= st.target_utilisation)
      errors.lower_threshold = "Must be below target utilisation";
  }
  return errors;
}
