"use client";

import { useMemo } from "react";
import { fmtMoney, fmtNum, fmtPct, fmtSeconds } from "@/lib/format";
import { toRows } from "@/lib/transform";
import type { SimulationResult } from "@/lib/types";
import { BarsChart, SERIES_COLORS, TimeChart } from "./charts";
import { Card, Stat } from "./ui";

export function RunAnalysis({ result }: { result: SimulationResult }) {
  const s = result.summary;
  const rows = useMemo(
    () =>
      toRows(result.timeseries).map((r) => ({
        ...r,
        utilisation_pct: r.utilisation === null ? null : r.utilisation * 100,
      })),
    [result],
  );
  const markers = result.scaling_events.map((e) => e.time_s / 60);
  const histogram = result.latency_histogram.counts.map((count, i) => ({
    bucket: `${result.latency_histogram.bin_edges[i].toFixed(2)}`,
    count,
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="P95 latency"
          value={fmtSeconds(s.latency.p95_s)}
          sub={`P99 ${fmtSeconds(s.latency.p99_s)} · mean ${fmtSeconds(s.latency.mean_s)}`}
        />
        <Stat
          label="SLA violations"
          value={fmtPct(s.sla_violation_pct)}
          sub={`${fmtNum(s.sla_violations)} of ${fmtNum(s.requests_total)} · threshold ${fmtSeconds(s.sla_threshold_s)}`}
        />
        <Stat
          label="Total cost"
          value={fmtMoney(s.total_cost)}
          sub={`${s.server_hours.toFixed(2)} server-h · ${fmtMoney(s.cost_per_completed_request === null ? null : s.cost_per_completed_request * 1000, 4)}/1k req`}
        />
        <Stat
          label="Mean utilisation"
          value={fmtPct(s.utilisation_mean, true)}
          sub={`${s.replicas_mean.toFixed(2)} replicas avg · peak ${s.replicas_peak}`}
        />
        <Stat
          label="Completed"
          value={fmtNum(s.requests_completed)}
          sub={`${s.throughput_rps.toFixed(2)} req/s`}
        />
        <Stat
          label="Unfinished / rejected"
          value={`${fmtNum(s.requests_unfinished)} / ${fmtNum(s.requests_rejected)}`}
          sub={`P95 incl. backlog ≥ ${fmtSeconds(s.latency_p95_lower_bound_s)}`}
        />
        <Stat
          label="Queue"
          value={s.queue_length_mean.toFixed(1)}
          sub={`time-weighted mean · peak ${fmtNum(s.queue_length_peak)}`}
        />
        <Stat
          label="Scaling events"
          value={`${s.scale_up_events} up / ${s.scale_down_events} down`}
          sub={`${s.servers_launched} launched · ${s.launches_cancelled} cancelled`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Workload vs capacity"
          subtitle="Arrival rate and nominal serving capacity per bucket"
        >
          <TimeChart
            data={rows}
            yLabel="req/s"
            digits={1}
            markers={markers}
            series={[
              { key: "arrival_rate_rps", label: "Arrival rate", color: SERIES_COLORS[0] },
              { key: "capacity_rps", label: "Capacity", color: SERIES_COLORS[1], kind: "step" },
            ]}
          />
        </Card>
        <Card title="Servers" subtitle="Server states at the end of each bucket">
          <TimeChart
            data={rows}
            yLabel="servers"
            digits={0}
            series={[
              {
                key: "active_end",
                label: "Active",
                color: SERIES_COLORS[0],
                kind: "area",
                stackId: "s",
              },
              {
                key: "starting_end",
                label: "Starting",
                color: SERIES_COLORS[1],
                kind: "area",
                stackId: "s",
              },
              {
                key: "draining_end",
                label: "Draining",
                color: SERIES_COLORS[2],
                kind: "area",
                stackId: "s",
              },
            ]}
          />
        </Card>
        <Card title="Response latency" subtitle="Requests completed in each bucket">
          <TimeChart
            data={rows}
            yLabel="seconds"
            digits={3}
            reference={{ value: s.sla_threshold_s, label: "SLA" }}
            series={[
              { key: "latency_mean_s", label: "Mean", color: SERIES_COLORS[0] },
              { key: "latency_p95_s", label: "P95", color: SERIES_COLORS[1] },
            ]}
          />
        </Card>
        <Card title="Queue length" subtitle="Time-weighted mean per bucket">
          <TimeChart
            data={rows}
            yLabel="requests"
            digits={1}
            series={[{ key: "queue_length_mean", label: "Queue", color: SERIES_COLORS[0] }]}
          />
        </Card>
        <Card title="Utilisation" subtitle="Busy slot-seconds / serving slot-seconds">
          <TimeChart
            data={rows}
            yLabel="%"
            digits={1}
            yDomain={[0, 100]}
            series={[{ key: "utilisation_pct", label: "Utilisation", color: SERIES_COLORS[0] }]}
          />
        </Card>
        <Card title="Cumulative compute cost">
          <TimeChart
            data={rows}
            yLabel="$"
            digits={3}
            series={[{ key: "cost_cumulative", label: "Cost", color: SERIES_COLORS[0] }]}
          />
        </Card>
        <Card
          title="SLA violations per bucket"
          subtitle="By completion time; rejections by arrival time"
        >
          <TimeChart
            data={rows}
            yLabel="requests"
            digits={0}
            series={[
              { key: "sla_violations", label: "Violations", color: SERIES_COLORS[1], kind: "area" },
            ]}
          />
        </Card>
        <Card title="Latency distribution" subtitle="Completed requests, bin lower edge in seconds">
          <BarsChart
            data={histogram}
            xKey="bucket"
            yLabel="requests"
            digits={0}
            series={[{ key: "count", label: "Requests", color: SERIES_COLORS[0] }]}
          />
        </Card>
      </div>

      <Card
        title="Scaling decisions"
        subtitle={`${result.scaling_events.length} changes to committed replicas (dashed lines on the workload chart)`}
      >
        {result.scaling_events.length === 0 ? (
          <p className="text-sm text-muted">The strategy never changed the replica count.</p>
        ) : (
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left text-sm tabular">
              <thead className="sticky top-0 bg-surface text-xs text-muted">
                <tr>
                  <th className="py-1.5 pr-4 font-medium">Time</th>
                  <th className="py-1.5 pr-4 font-medium">Replicas</th>
                  <th className="py-1.5 pr-4 font-medium">Actions</th>
                  <th className="py-1.5 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {result.scaling_events.map((e, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1.5 pr-4">{(e.time_s / 60).toFixed(2)} min</td>
                    <td className="py-1.5 pr-4">
                      {e.from_replicas} → {e.to_replicas}
                    </td>
                    <td className="py-1.5 pr-4 text-xs text-muted">
                      {[
                        e.launched && `+${e.launched} launched`,
                        e.reactivated && `${e.reactivated} reused`,
                        e.cancelled && `${e.cancelled} cancelled`,
                        e.terminated && `${e.terminated} stopped`,
                        e.drained && `${e.drained} draining`,
                      ]
                        .filter(Boolean)
                        .join(", ")}
                    </td>
                    <td className="py-1.5 text-xs text-muted">{e.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-xs text-muted">
        Simulated {fmtNum(result.runtime.events_processed)} events in{" "}
        {result.runtime.wall_time_ms.toFixed(0)} ms.
      </p>
    </div>
  );
}
