"use client";

import { useEffect, useState } from "react";
import { ApiError, getDefaults } from "@/lib/api";
import type { Defaults } from "@/lib/types";

export function useDefaults() {
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getDefaults(controller.signal)
      .then((d) => {
        setDefaults(d);
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err : new ApiError(0, "error", "Failed to load defaults"),
        );
      });
    return () => controller.abort();
  }, [attempt]);

  return { defaults, error, retry: () => setAttempt((a) => a + 1) };
}
