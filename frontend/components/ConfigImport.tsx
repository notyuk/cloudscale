"use client";

import { useRef, useState } from "react";
import type { Scenario, Strategy } from "@/lib/types";
import { Button } from "./ui";

export function ConfigImport({
  onLoad,
}: {
  onLoad: (scenario: Scenario, strategies: Strategy[] | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  async function handle(file: File) {
    try {
      const parsed = JSON.parse(await file.text());
      if (!parsed || typeof parsed.scenario !== "object") throw new Error();
      onLoad(
        parsed.scenario as Scenario,
        Array.isArray(parsed.strategies) ? parsed.strategies : null,
      );
      setError(null);
    } catch {
      setError("Not a CloudScale config file.");
    }
  }

  return (
    <>
      <Button onClick={() => input.current?.click()}>Load config</Button>
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        className="hidden"
        aria-label="Load config file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handle(file);
          e.target.value = "";
        }}
      />
      {error && (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      )}
    </>
  );
}
