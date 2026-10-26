"use client";

import type { ReactNode } from "react";
import { useConfig } from "./ConfigProvider";
import { ScenarioForm } from "./ScenarioForm";
import { Card, ErrorBanner, Spinner } from "./ui";
import type { Errors } from "@/lib/validation";

// Shared two-column layout: scenario + strategy config on the left, output on the right.
export function Workbench({
  title,
  description,
  scenarioErrors,
  controls,
  strategyPanel,
  children,
}: {
  title: string;
  description: string;
  scenarioErrors: Errors;
  controls: ReactNode;
  strategyPanel: ReactNode;
  children: ReactNode;
}) {
  const { defaults, loadError, retry, scenario, setScenario } = useConfig();

  if (loadError) return <ErrorBanner error={loadError} onRetry={retry} />;
  if (!defaults || !scenario) return <Spinner label="Loading defaults from the API…" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          <p className="text-sm text-muted">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">{controls}</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          {strategyPanel}
          <Card title="Scenario">
            <ScenarioForm
              scenario={scenario}
              onChange={setScenario}
              errors={scenarioErrors}
              patterns={defaults.workload_patterns}
            />
          </Card>
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
