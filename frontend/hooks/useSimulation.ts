"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, compareStrategies } from "@/lib/api";
import type { ComparisonResult, Scenario, Strategy } from "@/lib/types";

export type SimulationState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: ComparisonResult }
  | { status: "error"; error: ApiError };

export function useSimulation() {
  const [state, setState] = useState<SimulationState>({ status: "idle" });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(async (scenario: Scenario, strategies: Strategy[]) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setState({ status: "loading" });
    try {
      const data = await compareStrategies(scenario, strategies, current.signal);
      if (!current.signal.aborted) setState({ status: "success", data });
    } catch (err) {
      if (current.signal.aborted) return;
      setState({
        status: "error",
        error: err instanceof ApiError ? err : new ApiError(0, "error", String(err)),
      });
    }
  }, []);

  const cancel = useCallback(() => {
    controller.current?.abort();
    setState({ status: "idle" });
  }, []);

  return { state, run, cancel };
}
