"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { useDefaults } from "@/hooks/useDefaults";
import type { ApiError } from "@/lib/api";
import type { Defaults, Scenario, Strategy } from "@/lib/types";

interface ConfigValue {
  defaults: Defaults | null;
  loadError: ApiError | null;
  retry: () => void;
  scenario: Scenario | null;
  setScenario: (s: Scenario) => void;
  strategies: Strategy[];
  setStrategies: (s: Strategy[]) => void;
  reset: () => void;
}

const ConfigContext = createContext<ConfigValue | null>(null);

// Keeps the scenario and strategy list while moving between Simulator and Compare.
export function ConfigProvider({ children }: { children: ReactNode }) {
  const { defaults, error, retry } = useDefaults();
  // null means "not edited yet": fall back to the backend defaults.
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);

  const reset = () => {
    setScenario(null);
    setStrategies(null);
  };

  return (
    <ConfigContext.Provider
      value={{
        defaults,
        loadError: error,
        retry,
        scenario: scenario ?? defaults?.scenario ?? null,
        setScenario,
        strategies: strategies ?? defaults?.strategies ?? [],
        setStrategies,
        reset,
      }}
    >
      {children}
    </ConfigContext.Provider>
  );
}

export function useConfig(): ConfigValue {
  const value = useContext(ConfigContext);
  if (!value) throw new Error("useConfig must be used inside ConfigProvider");
  return value;
}
