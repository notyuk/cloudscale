// Same-origin proxy to the FastAPI backend. The target is read at request time,
// so one Docker image works with any backend address.

const ALLOWED = new Set([
  "health",
  "strategies",
  "config/defaults",
  "simulations/run",
  "simulations/compare",
]);
const TIMEOUT_MS = 120_000;

function backendUrl(): string {
  return (process.env.CLOUDSCALE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

async function forward(request: Request, path: string[]): Promise<Response> {
  const joined = path.join("/");
  if (!ALLOWED.has(joined)) {
    return Response.json(
      { error: "not_found", message: "Unknown API route.", details: [] },
      { status: 404 },
    );
  }
  try {
    const upstream = await fetch(`${backendUrl()}/${joined}`, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: request.method === "POST" ? await request.text() : undefined,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: "no-store",
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json(
      {
        error: "backend_unavailable",
        message: "The simulation backend is not reachable.",
        details: [],
      },
      { status: 502 },
    );
  }
}

export async function GET(request: Request, ctx: RouteContext<"/api/[...path]">) {
  return forward(request, (await ctx.params).path);
}

export async function POST(request: Request, ctx: RouteContext<"/api/[...path]">) {
  return forward(request, (await ctx.params).path);
}
