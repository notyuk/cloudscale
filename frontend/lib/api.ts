import type { ApiErrorDetail, ComparisonResult, Defaults, Scenario, Strategy } from "./types";

// Requests go through the Next.js route handler at /api, which forwards them to
// the backend. The browser therefore never needs the backend URL or CORS.
const BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body && typeof body.message === "string") {
      return new ApiError(
        response.status,
        body.error ?? "error",
        body.message,
        Array.isArray(body.details) ? body.details : [],
      );
    }
  } catch {
    // not JSON
  }
  return new ApiError(
    response.status,
    "http_error",
    `Request failed with status ${response.status}`,
  );
}

async function request<T>(
  path: string,
  init?: RequestInit,
  fetchImpl: typeof fetch = fetch,
): Promise<T> {
  let response: Response;
  try {
    response = await fetchImpl(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Could not reach the CloudScale API.");
  }
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export function getDefaults(signal?: AbortSignal): Promise<Defaults> {
  return request<Defaults>("/config/defaults", { signal });
}

export function compareStrategies(
  scenario: Scenario,
  strategies: Strategy[],
  signal?: AbortSignal,
): Promise<ComparisonResult> {
  return request<ComparisonResult>("/simulations/compare", {
    method: "POST",
    body: JSON.stringify({ scenario, strategies }),
    signal,
  });
}

export function describeDetail(detail: ApiErrorDetail): string {
  const path = detail.loc.filter((p) => p !== "body").join(".");
  return path ? `${path}: ${detail.msg}` : detail.msg;
}
