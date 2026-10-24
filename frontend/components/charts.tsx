"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Label,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

export const SERIES_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
];

export interface SeriesSpec {
  key: string;
  label: string;
  color: string;
  kind?: "line" | "area" | "step";
  stackId?: string;
  dashed?: boolean;
}

const axisTick = { fill: "var(--muted)", fontSize: 11 };
const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
    color: "var(--fg)",
  },
  labelStyle: { color: "var(--muted)" },
};

function formatValue(v: unknown, digits: number): string {
  return typeof v === "number" ? v.toFixed(digits) : "—";
}

export function TimeChart({
  data,
  series,
  yLabel,
  digits = 2,
  height = 220,
  reference,
  markers = [],
  yDomain,
}: {
  data: Record<string, number | null>[];
  series: SeriesSpec[];
  yLabel: string;
  digits?: number;
  height?: number;
  reference?: { value: number; label: string };
  markers?: number[];
  yDomain?: [number | "auto", number | "auto"];
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 16, left: 4 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="t_min"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={axisTick}
            tickFormatter={(v: number) => v.toFixed(0)}
            stroke="var(--border)"
          >
            <Label value="time (min)" position="insideBottom" offset={-10} style={axisTick} />
          </XAxis>
          <YAxis
            tick={axisTick}
            stroke="var(--border)"
            width={48}
            domain={yDomain ?? [0, "auto"]}
            allowDecimals
          >
            <Label
              value={yLabel}
              angle={-90}
              position="insideLeft"
              style={{ ...axisTick, textAnchor: "middle" }}
            />
          </YAxis>
          <Tooltip
            {...tooltipStyle}
            labelFormatter={(v) => `t = ${Number(v).toFixed(1)} min`}
            formatter={(v, name) => [formatValue(v, digits), name]}
          />
          {series.length > 1 && (
            <Legend
              itemSorter={null}
              verticalAlign="top"
              height={24}
              iconType="plainline"
              wrapperStyle={{ fontSize: 12 }}
            />
          )}
          {markers.map((m, i) => (
            <ReferenceLine key={`m${i}`} x={m} stroke="var(--border)" strokeDasharray="2 3" />
          ))}
          {reference && (
            <ReferenceLine
              y={reference.value}
              stroke="var(--reference)"
              strokeDasharray="4 4"
              label={{ value: reference.label, position: "insideTopRight", style: axisTick }}
            />
          )}
          {series.map((s) =>
            s.kind === "area" ? (
              <Area
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId={s.stackId}
                type="stepAfter"
                stroke={s.color}
                fill={s.color}
                fillOpacity={0.25}
                strokeWidth={1.5}
                isAnimationActive={false}
                connectNulls={false}
              />
            ) : (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.label}
                type={s.kind === "step" ? "stepAfter" : "monotone"}
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dashed ? "5 4" : undefined}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
                connectNulls={false}
              />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarsChart({
  data,
  series,
  yLabel,
  xKey,
  height = 220,
  digits = 1,
}: {
  data: Record<string, number | string | null>[];
  series: SeriesSpec[];
  yLabel: string;
  xKey: string;
  height?: number;
  digits?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={xKey} tick={axisTick} stroke="var(--border)" />
          <YAxis tick={axisTick} stroke="var(--border)" width={48}>
            <Label
              value={yLabel}
              angle={-90}
              position="insideLeft"
              style={{ ...axisTick, textAnchor: "middle" }}
            />
          </YAxis>
          <Tooltip
            {...tooltipStyle}
            cursor={{ fill: "var(--surface-2)" }}
            formatter={(v, name) => [formatValue(v, digits), name]}
          />
          {series.length > 1 && (
            <Legend
              itemSorter={null}
              verticalAlign="top"
              height={24}
              wrapperStyle={{ fontSize: 12 }}
            />
          )}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={s.color}
              radius={[4, 4, 0, 0]}
              stackId={s.stackId}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface ScatterPoint {
  label: string;
  x: number;
  y: number;
  color: string;
}

export function CostLatencyScatter({
  points,
  xLabel,
  yLabel,
  height = 260,
}: {
  points: ScatterPoint[];
  xLabel: string;
  yLabel: string;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 24, bottom: 20, left: 4 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis
            type="number"
            dataKey="x"
            tick={axisTick}
            stroke="var(--border)"
            domain={[0, "auto"]}
          >
            <Label value={xLabel} position="insideBottom" offset={-12} style={axisTick} />
          </XAxis>
          <YAxis
            type="number"
            dataKey="y"
            tick={axisTick}
            stroke="var(--border)"
            width={48}
            domain={[0, "auto"]}
          >
            <Label
              value={yLabel}
              angle={-90}
              position="insideLeft"
              style={{ ...axisTick, textAnchor: "middle" }}
            />
          </YAxis>
          <ZAxis range={[120, 120]} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v, name) => [formatValue(v, 3), name === "x" ? xLabel : yLabel]}
            labelFormatter={() => ""}
          />
          <Legend
            itemSorter={null}
            verticalAlign="top"
            height={24}
            wrapperStyle={{ fontSize: 12 }}
          />
          {points.map((p) => (
            <Scatter
              key={p.label}
              name={p.label}
              data={[p]}
              fill={p.color}
              stroke="var(--surface)"
              strokeWidth={2}
              isAnimationActive={false}
              label={{ dataKey: "label", position: "top", fill: "var(--muted)", fontSize: 11 }}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
