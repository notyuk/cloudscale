export function fmtSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return `${(value * 1000).toFixed(0)} ms`;
  if (value < 60) return `${value.toFixed(2)} s`;
  return `${(value / 60).toFixed(1)} min`;
}

export function fmtPct(value: number | null | undefined, fraction = false): string {
  if (value === null || value === undefined) return "—";
  return `${(fraction ? value * 100 : value).toFixed(1)}%`;
}

export function fmtMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(digits)}`;
}

export function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
