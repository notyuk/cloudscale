"use client";

import { downloadFile, summaryToCsv, timeseriesToCsv } from "@/lib/transform";
import type { ComparisonResult, Scenario, Strategy } from "@/lib/types";
import { Button } from "./ui";

export function ExportMenu({
  scenario,
  strategies,
  result,
}: {
  scenario: Scenario;
  strategies: Strategy[];
  result: ComparisonResult | null;
}) {
  const stamp = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return (
    <details className="group relative">
      <summary className="inline-flex cursor-pointer list-none items-center rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium hover:bg-surface-2">
        Export
      </summary>
      <div className="absolute right-0 z-10 mt-1 flex w-44 flex-col gap-1 rounded-md border border-border bg-surface p-1 shadow-lg [&>button]:justify-start [&>button]:border-0">
        <Button
          onClick={() =>
            downloadFile(
              `cloudscale-config-${stamp()}.json`,
              JSON.stringify({ scenario, strategies }, null, 2),
              "application/json",
            )
          }
        >
          Config JSON
        </Button>
        {result && (
          <>
            <Button
              onClick={() =>
                downloadFile(
                  `cloudscale-results-${stamp()}.json`,
                  JSON.stringify(result, null, 2),
                  "application/json",
                )
              }
            >
              Results JSON
            </Button>
            <Button
              onClick={() =>
                downloadFile(
                  `cloudscale-summary-${stamp()}.csv`,
                  summaryToCsv(result.results),
                  "text/csv",
                )
              }
            >
              Summary CSV
            </Button>
            <Button
              onClick={() =>
                downloadFile(
                  `cloudscale-timeseries-${stamp()}.csv`,
                  timeseriesToCsv(result.results),
                  "text/csv",
                )
              }
            >
              Time series CSV
            </Button>
          </>
        )}
      </div>
    </details>
  );
}
