"use client";

import { ComparisonView } from "@/components/ComparisonView";
import { useConfig } from "@/components/ConfigProvider";
import { ConfigImport } from "@/components/ConfigImport";
import { ExportMenu } from "@/components/ExportMenu";
import { StrategyForm } from "@/components/StrategyForm";
import { SERIES_COLORS } from "@/components/charts";
import { Button, Card, ErrorBanner, InvalidNotice, SelectField, Spinner } from "@/components/ui";
import { Workbench } from "@/components/Workbench";
import { useSimulation } from "@/hooks/useSimulation";
import { defaultStrategy, STRATEGY_LABELS } from "@/lib/presets";
import type { Strategy, StrategyType } from "@/lib/types";
import { validateScenario, validateStrategy } from "@/lib/validation";

export default function ComparePage() {
  const { defaults, scenario, setScenario, strategies, setStrategies, reset } = useConfig();
  const { state, run, cancel } = useSimulation();

  const scenarioErrors = scenario ? validateScenario(scenario) : {};
  const strategyErrors = scenario ? strategies.map((s) => validateStrategy(s, scenario)) : [];
  const labels = strategies.map((s) => s.label || s.type);
  const duplicate = new Set(labels).size !== labels.length;
  const errorCount =
    Object.keys(scenarioErrors).length +
    strategyErrors.reduce((n, e) => n + Object.keys(e).length, 0);
  const invalid = errorCount > 0 || strategies.length === 0 || duplicate;
  const loading = state.status === "loading";
  const max = defaults?.limits.max_compare_strategies ?? 5;

  const update = (i: number, s: Strategy) =>
    setStrategies(strategies.map((old, j) => (j === i ? s : old)));

  return (
    <Workbench
      title="Compare strategies"
      description="Every strategy is run on the same seeded trace with the same limits and prices."
      scenarioErrors={scenarioErrors}
      controls={
        scenario && (
          <>
            <ConfigImport
              onLoad={(s, list) => {
                setScenario(s);
                if (list?.length) setStrategies(list);
              }}
            />
            <ExportMenu
              scenario={scenario}
              strategies={strategies}
              result={state.status === "success" ? state.data : null}
            />
            <Button onClick={reset}>Reset to defaults</Button>
          </>
        )
      }
      strategyPanel={
        defaults && (
          <Card
            title="Strategies"
            subtitle={`Up to ${max}. Labels must be unique.`}
            actions={
              <Button
                disabled={strategies.length >= max}
                onClick={() =>
                  setStrategies([
                    ...strategies,
                    {
                      ...defaultStrategy("reactive", defaults.strategies),
                      label: `reactive ${strategies.length + 1}`,
                    },
                  ])
                }
              >
                Add
              </Button>
            }
          >
            <div className="space-y-5">
              {strategies.map((s, i) => (
                <div
                  key={i}
                  className="space-y-3 border-b border-border pb-5 last:border-0 last:pb-0"
                >
                  <div className="flex items-end gap-2">
                    <span
                      aria-hidden
                      className="mb-2.5 h-3 w-3 shrink-0 rounded-sm"
                      style={{ background: SERIES_COLORS[i] }}
                    />
                    <div className="flex-1">
                      <SelectField<StrategyType>
                        label={`Strategy ${i + 1}`}
                        value={s.type}
                        options={(["fixed", "reactive", "predictive"] as const).map((t) => ({
                          value: t,
                          label: STRATEGY_LABELS[t],
                        }))}
                        onChange={(t) => update(i, defaultStrategy(t, defaults.strategies))}
                      />
                    </div>
                    <Button
                      aria-label={`Remove strategy ${i + 1}`}
                      disabled={strategies.length <= 1}
                      onClick={() => setStrategies(strategies.filter((_, j) => j !== i))}
                    >
                      Remove
                    </Button>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-muted" htmlFor={`label-${i}`}>
                      Label (optional)
                    </label>
                    <input
                      id={`label-${i}`}
                      value={s.label ?? ""}
                      maxLength={40}
                      onChange={(e) => update(i, { ...s, label: e.target.value || null })}
                      className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
                    />
                  </div>
                  <StrategyForm
                    strategy={s}
                    onChange={(next) => update(i, next)}
                    errors={strategyErrors[i] ?? {}}
                  />
                </div>
              ))}
              {duplicate && (
                <p className="text-xs text-danger">
                  Give strategies of the same type distinct labels.
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  className="flex-1"
                  disabled={invalid || loading}
                  onClick={() => scenario && run(scenario, strategies)}
                >
                  {loading ? "Running…" : "Run comparison"}
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
            Press <strong>Run comparison</strong> to simulate every strategy against one shared
            trace.
          </p>
        </Card>
      )}
      {loading && (
        <Card>
          <Spinner label={`Simulating ${strategies.length} strategies…`} />
        </Card>
      )}
      {state.status === "error" && <ErrorBanner error={state.error} />}
      {state.status === "success" && <ComparisonView data={state.data} />}
    </Workbench>
  );
}
