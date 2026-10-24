"use client";

import type { Strategy } from "@/lib/types";
import type { Errors } from "@/lib/validation";
import { Checkbox, NumberField } from "./ui";

interface Props {
  strategy: Strategy;
  onChange: (s: Strategy) => void;
  errors: Errors;
}

export function StrategyForm({ strategy, onChange, errors }: Props) {
  const field = (key: string, label: string, unit?: string, step: number | "any" = "any") => (
    <NumberField
      key={key}
      label={label}
      unit={unit}
      step={step}
      value={(strategy as unknown as Record<string, number>)[key]}
      onChange={(v) => onChange({ ...strategy, [key]: v } as Strategy)}
      error={errors[key]}
    />
  );

  if (strategy.type === "fixed") {
    return <div className="grid grid-cols-2 gap-3">{field("replicas", "Replicas", "", 1)}</div>;
  }

  const common = [
    field("target_utilisation", "Target utilisation", "0–1"),
    field("lower_threshold", "Scale-down below", "0–1"),
    field("scale_up_cooldown_s", "Up cooldown", "s"),
    field("scale_down_cooldown_s", "Down cooldown", "s"),
    field("max_step_up", "Max step up", "", 1),
    field("max_step_down", "Max step down", "", 1),
  ];

  if (strategy.type === "reactive") {
    return (
      <div className="grid grid-cols-2 gap-3">
        {field("upper_threshold", "Scale-up above", "0–1")}
        {field("observation_window_s", "Window", "s")}
        {common}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {field("alpha", "Level α", "0–1")}
      {field("beta", "Trend β", "0–1")}
      <NumberField
        label="Horizon"
        unit="s"
        hint="Empty = delay + interval"
        value={strategy.horizon_s ?? NaN}
        onChange={(v) => onChange({ ...strategy, horizon_s: Number.isFinite(v) ? v : null })}
        error={errors.horizon_s}
      />
      {field("warmup_intervals", "Warm-up ticks", "", 1)}
      {common}
      <div className="col-span-2">
        <Checkbox
          label="Never size below current demand (reactive floor)"
          checked={strategy.reactive_floor}
          onChange={(v) => onChange({ ...strategy, reactive_floor: v })}
        />
      </div>
    </div>
  );
}
