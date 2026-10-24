import type { SimulationResult, TimeSeries } from "./types";

export type SeriesRow = { [K in keyof TimeSeries]: TimeSeries[K][number] } & {
  t_min: number;
};

export function toRows(ts: TimeSeries): SeriesRow[] {
  const keys = Object.keys(ts) as (keyof TimeSeries)[];
  return ts.t_start.map((t, i) => {
    const row = { t_min: t / 60 } as SeriesRow;
    for (const key of keys) {
      (row as Record<string, unknown>)[key] = ts[key][i];
    }
    return row;
  });
}

// One row per bucket with a column per strategy, e.g. { t_min, "reactive": 3 }.
export function mergeSeries(
  results: SimulationResult[],
  field: keyof TimeSeries,
): Record<string, number | null>[] {
  if (results.length === 0) return [];
  const base = results[0].timeseries;
  return base.t_start.map((t, i) => {
    const row: Record<string, number | null> = { t_min: t / 60 };
    for (const r of results) {
      row[r.strategy.label] = (r.timeseries[field][i] as number | null) ?? null;
    }
    return row;
  });
}

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function timeseriesToCsv(results: SimulationResult[]): string {
  if (results.length === 0) return "";
  const fields = Object.keys(results[0].timeseries) as (keyof TimeSeries)[];
  const lines = [["strategy", ...fields].join(",")];
  for (const r of results) {
    const ts = r.timeseries;
    for (let i = 0; i < ts.t_start.length; i++) {
      lines.push([r.strategy.label, ...fields.map((f) => ts[f][i])].map(csvCell).join(","));
    }
  }
  return lines.join("\n") + "\n";
}

export function summaryToCsv(results: SimulationResult[]): string {
  const rows: Record<string, unknown>[] = results.map((r) => ({
    strategy: r.strategy.label,
    ...flatten(r.summary),
  }));
  if (rows.length === 0) return "";
  const header = Object.keys(rows[0]);
  return (
    [header.join(","), ...rows.map((row) => header.map((h) => csvCell(row[h])).join(","))].join(
      "\n",
    ) + "\n"
  );
}

function flatten(obj: object, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const name = prefix ? `${prefix}_${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.assign(out, flatten(value, name));
    } else {
      out[name] = value;
    }
  }
  return out;
}

export function downloadFile(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
