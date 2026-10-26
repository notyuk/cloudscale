"use client";

import { PATTERN_LABELS, WORKLOAD_PRESETS } from "@/lib/presets";
import type { Scenario, Workload, WorkloadPattern } from "@/lib/types";
import type { Errors } from "@/lib/validation";
import { NumberField, SelectField } from "./ui";

interface Props {
  scenario: Scenario;
  onChange: (s: Scenario) => void;
  errors: Errors;
  patterns: WorkloadPattern[];
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        {title}
      </legend>
      <div className="grid grid-cols-2 gap-3">{children}</div>
    </fieldset>
  );
}

export function ScenarioForm({ scenario, onChange, errors, patterns }: Props) {
  const w = scenario.workload;
  const set = (patch: Partial<Scenario>) => onChange({ ...scenario, ...patch });
  const setWorkload = (patch: Record<string, number>) =>
    set({ workload: { ...w, ...patch } as Workload });
  const setCluster = (patch: Partial<Scenario["cluster"]>) =>
    set({ cluster: { ...scenario.cluster, ...patch } });

  const wf = (key: string, label: string, unit?: string, hint?: string) => (
    <NumberField
      key={key}
      label={label}
      unit={unit}
      hint={hint}
      value={(w as unknown as Record<string, number>)[key]}
      onChange={(v) => setWorkload({ [key]: v })}
      error={errors[`workload.${key}`]}
    />
  );

  return (
    <div className="space-y-6">
      <Group title="Workload">
        <div className="col-span-2">
          <SelectField
            label="Pattern"
            value={w.pattern}
            options={patterns.map((p) => ({ value: p, label: PATTERN_LABELS[p] }))}
            onChange={(p) => set({ workload: WORKLOAD_PRESETS[p] })}
          />
        </div>
        {(w.pattern === "constant" || w.pattern === "poisson") && wf("rate", "Rate", "req/s")}
        {w.pattern === "sinusoidal" && [
          wf("base_rate", "Base rate", "req/s"),
          wf("amplitude", "Amplitude", "req/s"),
          wf("period_s", "Period", "s"),
          wf("phase_rad", "Phase", "rad"),
        ]}
        {w.pattern === "spike" && [
          wf("base_rate", "Base rate", "req/s"),
          wf("spike_rate", "Spike rate", "req/s"),
          wf("spike_start_s", "Spike start", "s"),
          wf("spike_duration_s", "Spike length", "s"),
        ]}
        {w.pattern === "ramp" && [
          wf("start_rate", "Start rate", "req/s"),
          wf("end_rate", "End rate", "req/s"),
        ]}
        {w.pattern === "bursty" && [
          wf("base_rate", "Base rate", "req/s"),
          wf("peak_multiplier", "Burst multiplier", "×"),
          wf("mean_burst_s", "Mean burst", "s"),
          wf("mean_gap_s", "Mean gap", "s"),
        ]}
        <NumberField
          label="Duration"
          unit="s"
          value={scenario.duration_s}
          onChange={(v) => set({ duration_s: v })}
          error={errors.duration_s}
        />
        <NumberField
          label="Random seed"
          step={1}
          value={scenario.seed}
          onChange={(v) => set({ seed: v })}
          error={errors.seed}
        />
      </Group>

      <Group title="Requests">
        <div className="col-span-2">
          <SelectField
            label="Work distribution"
            value={scenario.service.distribution}
            options={[
              { value: "constant", label: "Constant" },
              { value: "exponential", label: "Exponential" },
              { value: "lognormal", label: "Log-normal" },
            ]}
            onChange={(d) => set({ service: { ...scenario.service, distribution: d } })}
          />
        </div>
        <NumberField
          label="Mean work"
          unit="units"
          hint="1 unit = 1 s on a speed-1 slot"
          value={scenario.service.mean_work}
          onChange={(v) => set({ service: { ...scenario.service, mean_work: v } })}
          error={errors["service.mean_work"]}
        />
        {scenario.service.distribution === "lognormal" && (
          <NumberField
            label="Coeff. of variation"
            value={scenario.service.cv}
            onChange={(v) => set({ service: { ...scenario.service, cv: v } })}
            error={errors["service.cv"]}
          />
        )}
      </Group>

      <Group title="Cluster">
        <NumberField
          label="Slots per server"
          step={1}
          value={scenario.cluster.slots_per_server}
          onChange={(v) => setCluster({ slots_per_server: v })}
          error={errors["cluster.slots_per_server"]}
        />
        <NumberField
          label="Server speed"
          unit="units/s"
          value={scenario.cluster.server_speed}
          onChange={(v) => setCluster({ server_speed: v })}
          error={errors["cluster.server_speed"]}
        />
        <NumberField
          label="Min replicas"
          step={1}
          value={scenario.cluster.min_replicas}
          onChange={(v) => setCluster({ min_replicas: v })}
          error={errors["cluster.min_replicas"]}
        />
        <NumberField
          label="Max replicas"
          step={1}
          value={scenario.cluster.max_replicas}
          onChange={(v) => setCluster({ max_replicas: v })}
          error={errors["cluster.max_replicas"]}
        />
        <NumberField
          label="Initial replicas"
          step={1}
          value={scenario.cluster.initial_replicas}
          onChange={(v) => setCluster({ initial_replicas: v })}
          error={errors["cluster.initial_replicas"]}
        />
        <NumberField
          label="Provisioning delay"
          unit="s"
          value={scenario.cluster.provisioning_delay_s}
          onChange={(v) => setCluster({ provisioning_delay_s: v })}
          error={errors["cluster.provisioning_delay_s"]}
        />
        <NumberField
          label="Queue capacity"
          step={1}
          value={scenario.cluster.max_pending}
          onChange={(v) => setCluster({ max_pending: v })}
          error={errors["cluster.max_pending"]}
        />
        <NumberField
          label="Control interval"
          unit="s"
          value={scenario.control_interval_s}
          onChange={(v) => set({ control_interval_s: v })}
          error={errors.control_interval_s}
        />
      </Group>

      <Group title="SLA & cost">
        <NumberField
          label="Latency threshold"
          unit="s"
          value={scenario.sla.latency_threshold_s}
          onChange={(v) => set({ sla: { ...scenario.sla, latency_threshold_s: v } })}
          error={errors["sla.latency_threshold_s"]}
        />
        <NumberField
          label="Penalty / violation"
          unit="$"
          value={scenario.sla.penalty_per_violation}
          onChange={(v) => set({ sla: { ...scenario.sla, penalty_per_violation: v } })}
          error={errors["sla.penalty_per_violation"]}
        />
        <NumberField
          label="Server price"
          unit="$/h"
          value={scenario.cost.server_price_per_hour}
          onChange={(v) => set({ cost: { server_price_per_hour: v } })}
          error={errors["cost.server_price_per_hour"]}
        />
        <NumberField
          label="Chart bucket"
          unit="s"
          value={scenario.metrics_interval_s}
          onChange={(v) => set({ metrics_interval_s: v })}
          error={errors.metrics_interval_s}
        />
      </Group>
    </div>
  );
}
