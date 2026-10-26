import type { Strategy, StrategyType, Workload, WorkloadPattern } from "./types";

// Starting values when the user switches pattern. They match the backend defaults.
export const WORKLOAD_PRESETS: Record<WorkloadPattern, Workload> = {
  constant: { pattern: "constant", rate: 20 },
  poisson: { pattern: "poisson", rate: 20 },
  sinusoidal: {
    pattern: "sinusoidal",
    base_rate: 20,
    amplitude: 15,
    period_s: 600,
    phase_rad: 0,
  },
  spike: {
    pattern: "spike",
    base_rate: 10,
    spike_rate: 60,
    spike_start_s: 600,
    spike_duration_s: 300,
  },
  ramp: { pattern: "ramp", start_rate: 5, end_rate: 50 },
  bursty: {
    pattern: "bursty",
    base_rate: 10,
    peak_multiplier: 5,
    mean_burst_s: 60,
    mean_gap_s: 300,
  },
};

export const PATTERN_LABELS: Record<WorkloadPattern, string> = {
  constant: "Constant (evenly spaced)",
  poisson: "Poisson",
  sinusoidal: "Sinusoidal / periodic",
  spike: "Sudden spike",
  ramp: "Gradual ramp",
  bursty: "Bursty (MMPP)",
};

export const STRATEGY_LABELS: Record<StrategyType, string> = {
  fixed: "Fixed capacity",
  reactive: "Reactive",
  predictive: "Predictive (Holt)",
};

export const STRATEGY_BLURBS: Record<StrategyType, string> = {
  fixed:
    "Holds a constant number of warm servers. No provisioning delay and no reaction to load, so its cost is predictable but it either over-pays or saturates.",
  reactive:
    "Scales when windowed utilisation leaves the hysteresis band. It only reacts after load has arrived, so a spike is absorbed by queueing until new servers finish booting.",
  predictive:
    "Forecasts the arrival rate one provisioning delay ahead with Holt's method. It is good at sustained trends, but it overshoots after a spike ends and is noisy at low rates.",
};

export function defaultStrategy(type: StrategyType, defaults: Strategy[]): Strategy {
  const found = defaults.find((s) => s.type === type);
  if (found) return { ...found };
  throw new Error(`no defaults for strategy ${type}`);
}
