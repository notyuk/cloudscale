"use client";

import { useState } from "react";
import { useConfig } from "@/components/ConfigProvider";
import { ConfigImport } from "@/components/ConfigImport";
import { ExportMenu } from "@/components/ExportMenu";
import { RunAnalysis } from "@/components/RunAnalysis";
import { StrategyForm } from "@/components/StrategyForm";
import { Button, Card, ErrorBanner, InvalidNotice, SelectField, Spinner } from "@/components/ui";
import { Workbench } from "@/components/Workbench";
import { useSimulation } from "@/hooks/useSimulation";
import { defaultStrategy, STRATEGY_LABELS } from "@/lib/presets";
import type { Strategy, StrategyType } from "@/lib/types";
import { validateScenario, validateStrategy } from "@/lib/validation";

export default function SimulatePage() {
  const { defaults, scenario, setScenario, reset } = useConfig();
  const { state, run, cancel } = useSimulation();
  const [strategy, setStrategy] = useState<Strategy | null>(null);

  const current = strategy ?? (defaults ? defaultStrategy("reactive", defaults.strategies) : null);
  const scenarioErrors = scenario ? validateScenario(scenario) : {};
  const strategyErrors = scenario && current ? validateStrategy(current, scenario) : {};
  const errorCount = Object.keys(scenarioErrors).length + Object.keys(strategyErrors).length;
  const invalid = errorCount > 0;
  const loading = state.status === "loading";

  return (
    <Workbench
      title="Simulator"
      description="Run one strategy and inspect its behaviour over time."
      scenarioErrors={scenarioErrors}
      controls={
        scenario &&
        current && (
          <>
            <ConfigImport
              onLoad={(s, list) => {
                setScenario(s);
                if (list?.[0]) setStrategy(list[0]);
              }}
            />
            <ExportMenu
              scenario={scenario}
              strategies={[current]}
              result={state.status === "success" ? state.data : null}
            />
            <Button
              onClick={() => {
                reset();
                setStrategy(null);
              }}
            >
              Reset to defaults
            </Button>
          </>
        )
      }
      strategyPanel={
        defaults &&
        current && (
          <Card title="Strategy">
            <div className="space-y-4">
              <SelectField<StrategyType>
                label="Type"
                value={current.type}
                options={(["fixed", "reactive", "predictive"] as const).map((t) => ({
                  value: t,
                  label: STRATEGY_LABELS[t],
                }))}
                onChange={(t) => setStrategy(defaultStrategy(t, defaults.strategies))}
              />
              <StrategyForm strategy={current} onChange={setStrategy} errors={strategyErrors} />
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  className="flex-1"
                  disabled={invalid || loading}
                  onClick={() => scenario && run(scenario, [current])}
                >
                  {loading ? "Running…" : "Run simulation"}
                </Button>
                {loading && <Button onClick={cancel}>Cancel</Button>}
              </div>
              <InvalidNotice count={errorCount} />
            </div>
          </Card>
        )
      }
    >
      {state.status === "idle" && (
        <Card>
          <p className="text-sm text-muted">
            Configure a scenario and press <strong>Run simulation</strong>. Every chart is drawn
            from the backend&apos;s simulation output for that run.
          </p>
        </Card>
      )}
      {loading && (
        <Card>
          <Spinner label="Simulating…" />
        </Card>
      )}
      {state.status === "error" && <ErrorBanner error={state.error} />}
      {state.status === "success" && state.data.results[0] && (
        <RunAnalysis result={state.data.results[0]} />
      )}
    </Workbench>
  );
}
