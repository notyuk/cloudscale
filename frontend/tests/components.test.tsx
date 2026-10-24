import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ComparisonTable } from "@/components/ComparisonView";
import { ScenarioForm } from "@/components/ScenarioForm";
import { ErrorBanner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import type { Scenario } from "@/lib/types";
import { validateScenario } from "@/lib/validation";
import { result, scenario } from "./fixtures";

function FormHarness() {
  const [value, setValue] = useState<Scenario>(scenario);
  return (
    <ScenarioForm
      scenario={value}
      onChange={setValue}
      errors={validateScenario(value)}
      patterns={["constant", "poisson", "sinusoidal", "spike", "ramp", "bursty"]}
    />
  );
}

describe("ComparisonTable", () => {
  it("renders one column per strategy and marks the best value", () => {
    render(
      <ComparisonTable
        results={[result("cheap", { total_cost: 0.1 }), result("pricey", { total_cost: 0.5 })]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: /cheap/ })).toBeInTheDocument();
    const costRow = screen.getByRole("row", { name: /Total cost/ });
    const cells = within(costRow).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("$0.10 (best)");
    expect(cells[1]).toHaveTextContent("$0.50");
    expect(cells[1]).not.toHaveTextContent("best");
  });

  it("shows a dash for metrics with no data", () => {
    render(
      <ComparisonTable
        results={[
          result("a", {
            latency: { mean_s: null, median_s: null, p95_s: null, p99_s: null, max_s: null },
          }),
        ]}
      />,
    );
    const row = screen.getByRole("row", { name: /P95 latency/ });
    expect(within(row).getByRole("cell")).toHaveTextContent("—");
  });

  it("does not highlight ties", () => {
    render(<ComparisonTable results={[result("a"), result("b")]} />);
    expect(screen.queryByText(/\(best\)/)).toBeNull();
  });
});

describe("ScenarioForm", () => {
  it("switches workload fields with the pattern", async () => {
    render(<FormHarness />);
    expect(screen.getByLabelText(/Amplitude/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Pattern"), "spike");
    expect(screen.queryByLabelText(/Amplitude/)).toBeNull();
    expect(screen.getByLabelText(/Spike rate/)).toHaveValue(60);
  });

  it("shows inline validation errors", async () => {
    render(<FormHarness />);
    const minReplicas = screen.getByLabelText("Min replicas");
    await userEvent.clear(minReplicas);
    await userEvent.type(minReplicas, "30");
    expect(screen.getByText("Must be ≥ min replicas")).toBeInTheDocument();
    expect(screen.getByLabelText(/Max replicas/)).toHaveAttribute("aria-invalid", "true");
  });

  it("treats a cleared field as required", async () => {
    render(<FormHarness />);
    await userEvent.clear(screen.getByLabelText(/Duration/));
    expect(screen.getByText("Required")).toBeInTheDocument();
  });
});

describe("ErrorBanner", () => {
  it("lists validation details from the API", () => {
    render(
      <ErrorBanner
        error={
          new ApiError(422, "validation_error", "The request body failed validation.", [
            { loc: ["body", "scenario", "seed"], msg: "must be >= 0", type: "x" },
          ])
        }
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("scenario.seed: must be >= 0");
  });
});
