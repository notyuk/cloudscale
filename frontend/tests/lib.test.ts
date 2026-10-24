import { describe, expect, it, vi } from "vitest";
import { ApiError, compareStrategies, describeDetail, parseError } from "@/lib/api";
import { fmtMoney, fmtPct, fmtSeconds } from "@/lib/format";
import { mergeSeries, summaryToCsv, timeseriesToCsv, toRows } from "@/lib/transform";
import { validateScenario, validateStrategy } from "@/lib/validation";
import { result, scenario } from "./fixtures";

describe("transform", () => {
  it("turns columnar series into rows with minutes", () => {
    const rows = toRows(result("a").timeseries);
    expect(rows).toHaveLength(3);
    expect(rows[1].t_min).toBe(1);
    expect(rows[1].arrivals).toBe(11);
    expect(rows[1].latency_mean_s).toBeNull();
  });

  it("merges one field across strategies by label", () => {
    const merged = mergeSeries([result("a"), result("b")], "cost_cumulative");
    expect(merged[2]).toEqual({ t_min: 2, a: 0.03, b: 0.03 });
  });

  it("writes CSV with one row per strategy and bucket", () => {
    const csv = timeseriesToCsv([result("a"), result("b")])
      .trim()
      .split("\n");
    expect(csv[0].startsWith("strategy,t_start,t_end,arrivals")).toBe(true);
    expect(csv).toHaveLength(1 + 2 * 3);
    // null latency becomes an empty cell rather than "null"
    expect(csv[2]).not.toContain("null");
  });

  it("quotes CSV cells containing commas", () => {
    const csv = summaryToCsv([result("fixed, 3")]);
    expect(csv.split("\n")[1].startsWith('"fixed, 3",')).toBe(true);
    expect(csv.split("\n")[0]).toContain("latency_p95_s");
  });
});

describe("format", () => {
  it("formats nulls as a dash", () => {
    expect(fmtSeconds(null)).toBe("—");
    expect(fmtPct(null)).toBe("—");
    expect(fmtMoney(undefined)).toBe("—");
  });

  it("picks sensible units", () => {
    expect(fmtSeconds(0.25)).toBe("250 ms");
    expect(fmtSeconds(2.5)).toBe("2.50 s");
    expect(fmtSeconds(150)).toBe("2.5 min");
    expect(fmtPct(0.123, true)).toBe("12.3%");
  });
});

describe("validation", () => {
  it("accepts the defaults", () => {
    expect(validateScenario(scenario)).toEqual({});
  });

  it("flags inconsistent replica bounds", () => {
    const errors = validateScenario({
      ...scenario,
      cluster: { ...scenario.cluster, min_replicas: 5, max_replicas: 3, initial_replicas: 4 },
    });
    expect(errors["cluster.max_replicas"]).toBeDefined();
    expect(errors["cluster.initial_replicas"]).toBeDefined();
  });

  it("flags empty fields and workload rules", () => {
    const errors = validateScenario({
      ...scenario,
      duration_s: NaN,
      workload: { pattern: "sinusoidal", base_rate: 5, amplitude: 10, period_s: 60, phase_rad: 0 },
    });
    expect(errors.duration_s).toBe("Required");
    expect(errors["workload.amplitude"]).toMatch(/base rate/);
  });

  it("checks fixed replicas against the cluster", () => {
    expect(validateStrategy({ type: "fixed", replicas: 50 }, scenario).replicas).toBeDefined();
  });

  it("requires ordered reactive thresholds", () => {
    const errors = validateStrategy(
      {
        type: "reactive",
        upper_threshold: 0.5,
        lower_threshold: 0.3,
        target_utilisation: 0.6,
        observation_window_s: 60,
        scale_up_cooldown_s: 60,
        scale_down_cooldown_s: 300,
        max_step_up: 10,
        max_step_down: 2,
        backlog_drain_s: 30,
      },
      scenario,
    );
    expect(errors.target_utilisation).toBeDefined();
  });
});

describe("api", () => {
  it("parses the backend error envelope", async () => {
    const response = new Response(
      JSON.stringify({
        error: "validation_error",
        message: "bad",
        details: [{ loc: ["body", "scenario", "duration_s"], msg: "too big", type: "x" }],
      }),
      { status: 422 },
    );
    const err = await parseError(response);
    expect(err.code).toBe("validation_error");
    expect(describeDetail(err.details[0])).toBe("scenario.duration_s: too big");
  });

  it("falls back for non-JSON errors", async () => {
    const err = await parseError(new Response("oops", { status: 502 }));
    expect(err.message).toMatch(/502/);
  });

  it("reports network failures as ApiError", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("down"));
    await expect(compareStrategies(scenario, [])).rejects.toBeInstanceOf(ApiError);
    spy.mockRestore();
  });

  it("posts scenario and strategies to the compare endpoint", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ results: [] }), { status: 200 }));
    await compareStrategies(scenario, [{ type: "fixed", replicas: 2 }]);
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe("/api/simulations/compare");
    expect(JSON.parse(String(init?.body)).strategies[0].replicas).toBe(2);
    spy.mockRestore();
  });
});
