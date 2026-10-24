"use client";

import { useMemo } from "react";
import { fmtMoney, fmtNum, fmtPct, fmtSeconds } from "@/lib/format";
import { STRATEGY_BLURBS, STRATEGY_LABELS } from "@/lib/presets";
import { mergeSeries } from "@/lib/transform";
import type { ComparisonResult, SimulationResult, Summary } from "@/lib/types";
import { BarsChart, CostLatencyScatter, SERIES_COLORS, TimeChart, type SeriesSpec } from "./charts";
import { Card } from "./ui";

type Column = {
  label: string;
  value: (s: Summary) => number | null;
  format: (v: number | null) => string;
  better: "low" | "high";
};

const COLUMNS: Column[] = [
  { label: "P95 latency", value: (s) => s.latency.p95_s, format: fmtSeconds, better: "low" },
  { label: "P99 latency", value: (s) => s.latency.p99_s, format: fmtSeconds, better: "low" },
  { label: "Mean latency", value: (s) => s.latency.mean_s, format: fmtSeconds, better: "low" },
  {
    label: "SLA violations",
    value: (s) => s.sla_violation_pct,
    format: (v) => fmtPct(v),
    better: "low",
  },
  { label: "Total cost", value: (s) => s.total_cost, format: (v) => fmtMoney(v), better: "low" },
  {
    label: "Cost / 1k requests",
    value: (s) =>
      s.cost_per_completed_request === null ? null : s.cost_per_completed_request * 1000,
    format: (v) => fmtMoney(v, 4),
    better: "low",
  },
  {
    label: "Throughput",
    value: (s) => s.throughput_rps,
    format: (v) => (v === null ? "—" : `${v.toFixed(2)}/s`),
    better: "high",
  },
  {
    label: "Utilisation",
    value: (s) => s.utilisation_mean,
    format: (v) => fmtPct(v, true),
    better: "high",
  },
  {
    label: "Mean replicas",
    value: (s) => s.replicas_mean,
    format: (v) => (v === null ? "—" : v.toFixed(2)),
    better: "low",
  },
  {
    label: "Peak queue",
    value: (s) => s.queue_length_peak,
    format: (v) => fmtNum(v),
    better: "low",
  },
  {
    label: "Unfinished",
    value: (s) => s.requests_unfinished,
    format: (v) => fmtNum(v),
    better: "low",
  },
  { label: "Rejected", value: (s) => s.requests_rejected, format: (v) => fmtNum(v), better: "low" },
  {
    label: "Scale events",
    value: (s) => s.scale_up_events + s.scale_down_events,
    format: (v) => fmtNum(v),
    better: "low",
  },
];

function bestIndex(results: SimulationResult[], col: Column): number | null {
  const values = results.map((r) => col.value(r.summary));
  let best: number | null = null;
  values.forEach((v, i) => {
    if (v === null) return;
    const current = best === null ? null : values[best];
    if (current === null || (col.better === "low" ? v < current! : v > current!)) best = i;
  });
  // Don't highlight a tie across every strategy.
  if (best !== null && values.every((v) => v === values[best!])) return null;
  return best;
}

export function ComparisonTable({ results }: { results: SimulationResult[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm tabular">
        <thead className="text-xs text-muted">
          <tr>
            <th className="py-2 pr-4 font-medium">Metric</th>
            {results.map((r, i) => (
              <th key={r.strategy.label} className="py-2 pr-4 font-medium">
                <span className="inline-flex items-center gap-2">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 rounded-sm"
                    style={{ background: SERIES_COLORS[i] }}
                  />
                  {r.strategy.label}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {COLUMNS.map((col) => {
            const best = bestIndex(results, col);
            return (
              <tr key={col.label} className="border-t border-border">
                <th scope="row" className="py-1.5 pr-4 font-normal text-muted">
                  {col.label}
                </th>
                {results.map((r, i) => (
                  <td
                    key={r.strategy.label}
                    className={`py-1.5 pr-4 ${i === best ? "font-semibold" : ""}`}
                  >
                    {col.format(col.value(r.summary))}
                    {i === best && <span className="sr-only"> (best)</span>}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">Bold marks the best value in each row.</p>
    </div>
  );
}

function Findings({ results }: { results: SimulationResult[] }) {
  if (results.length < 2) return null;
  const by = (f: (s: Summary) => number | null) =>
    results.filter((r) => f(r.summary) !== null).sort((a, b) => f(a.summary)! - f(b.summary)!);
  const cheapest = by((s) => s.total_cost)[0];
  const fastest = by((s) => s.latency.p95_s)[0];
  const compliant = by((s) => s.sla_violation_pct)[0];
  const backlog = results.filter(
    (r) => r.summary.requests_unfinished > r.summary.requests_total * 0.01,
  );
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {cheapest && (
        <li>
          Lowest total cost: <strong>{cheapest.strategy.label}</strong> (
          {fmtMoney(cheapest.summary.total_cost)}).
        </li>
      )}
      {fastest && (
        <li>
          Lowest P95 latency: <strong>{fastest.strategy.label}</strong> (
          {fmtSeconds(fastest.summary.latency.p95_s)}).
        </li>
      )}
      {compliant && (
        <li>
          Fewest SLA violations: <strong>{compliant.strategy.label}</strong> (
          {fmtPct(compliant.summary.sla_violation_pct)}).
        </li>
      )}
      {backlog.map((r) => (
        <li key={r.strategy.label}>
          <strong>{r.strategy.label}</strong> ended with {fmtNum(r.summary.requests_unfinished)}{" "}
          unfinished requests, so its completed-request latency understates the delay. The
          backlog-inclusive P95 is at least {fmtSeconds(r.summary.latency_p95_lower_bound_s)}.
        </li>
      ))}
    </ul>
  );
}

export function ComparisonView({ data }: { data: ComparisonResult }) {
  const { results } = data;
  const specs: SeriesSpec[] = results.map((r, i) => ({
    key: r.strategy.label,
    label: r.strategy.label,
    color: SERIES_COLORS[i],
  }));

  const charts = useMemo(() => {
    const capacity = mergeSeries(results, "capacity_rps");
    const arrivals = results[0]?.timeseries.arrival_rate_rps ?? [];
    return {
      overlay: capacity.map((row, i) => ({ ...row, __arrivals: arrivals[i] })),
      replicas: mergeSeries(results, "replicas_mean"),
      p95: mergeSeries(results, "latency_p95_s"),
      queue: mergeSeries(results, "queue_length_mean"),
      cost: mergeSeries(results, "cost_cumulative"),
    };
  }, [results]);

  const threshold = data.scenario.sla.latency_threshold_s;
  const sla = results.map((r) => ({
    strategy: r.strategy.label,
    compliant: r.summary.sla_violation_pct === null ? null : 100 - r.summary.sla_violation_pct,
  }));
  const types = Array.from(new Set(results.map((r) => r.strategy.config.type)));

  return (
    <div className="space-y-4">
      <Card
        title="Summary"
        subtitle={`${fmtNum(data.requests_generated)} requests, the same seeded trace for every strategy`}
      >
        <ComparisonTable results={results} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Cost vs P95 latency" subtitle="Lower left is better">
          <CostLatencyScatter
            xLabel="total cost ($)"
            yLabel="P95 latency (s)"
            points={results
              .filter((r) => r.summary.latency.p95_s !== null)
              .map((r) => ({
                label: r.strategy.label,
                x: r.summary.total_cost,
                y: r.summary.latency.p95_s!,
                color: SERIES_COLORS[results.indexOf(r)],
              }))}
          />
        </Card>
        <Card title="Findings" subtitle="Computed from these results">
          <Findings results={results} />
          <div className="mt-4 space-y-2 border-t border-border pt-3 text-xs text-muted">
            {types.map((t) => (
              <p key={t}>
                <span className="font-medium text-fg">{STRATEGY_LABELS[t]}.</span>{" "}
                {STRATEGY_BLURBS[t]}
              </p>
            ))}
          </div>
        </Card>
        <Card
          title="Workload and capacity"
          subtitle="Arrival rate (dashed) vs each strategy's serving capacity"
        >
          <TimeChart
            data={charts.overlay}
            yLabel="req/s"
            digits={1}
            series={[
              { key: "__arrivals", label: "Arrival rate", color: "var(--reference)", dashed: true },
              ...specs.map((s) => ({ ...s, kind: "step" as const })),
            ]}
          />
        </Card>
        <Card title="Replicas" subtitle="Time-weighted billed servers per bucket">
          <TimeChart data={charts.replicas} yLabel="servers" digits={2} series={specs} />
        </Card>
        <Card title="P95 latency" subtitle="Requests completed in each bucket">
          <TimeChart
            data={charts.p95}
            yLabel="seconds"
            digits={3}
            reference={{ value: threshold, label: "SLA" }}
            series={specs}
          />
        </Card>
        <Card title="Queue length" subtitle="Time-weighted mean per bucket">
          <TimeChart data={charts.queue} yLabel="requests" digits={1} series={specs} />
        </Card>
        <Card title="SLA compliance" subtitle="% of evaluable requests within the threshold">
          <BarsChart
            data={sla}
            xKey="strategy"
            yLabel="%"
            series={[{ key: "compliant", label: "Compliant", color: SERIES_COLORS[0] }]}
          />
        </Card>
        <Card title="Cumulative compute cost">
          <TimeChart data={charts.cost} yLabel="$" digits={3} series={specs} />
        </Card>
      </div>
    </div>
  );
}
