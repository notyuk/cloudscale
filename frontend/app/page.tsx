import Link from "next/link";

const STEPS = [
  {
    title: "Workload",
    body: "A seeded generator produces the arrival times and per-request work. Six patterns are available: constant, Poisson, sinusoidal, spike, ramp and bursty (MMPP).",
  },
  {
    title: "Event engine",
    body: "A discrete-event simulator with a logical clock. Requests wait in one FIFO queue in front of servers that each have a fixed number of slots, and new servers take a provisioning delay before they accept work.",
  },
  {
    title: "Strategy",
    body: "Every control interval an autoscaler sees only past observations and asks for a replica count. The engine enforces min/max bounds, provisioning delays and draining.",
  },
  {
    title: "Metrics",
    body: "Latency percentiles, SLA violations (including unfinished and rejected requests), time-weighted queue and utilisation, and cost in billed server-hours.",
  },
];

export default function Overview() {
  return (
    <div className="mx-auto max-w-3xl space-y-10 py-4">
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight">
          Compare autoscaling strategies on identical, reproducible traffic.
        </h1>
        <p className="text-muted">
          CloudScale simulates a pool of servers behind a load balancer and measures how fixed,
          reactive and predictive autoscalers trade cost against latency. Runs are deterministic:
          the same configuration and seed always give the same result.
        </p>
        <div className="flex gap-3">
          <Link
            href="/compare"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90"
          >
            Compare strategies
          </Link>
          <Link
            href="/simulate"
            className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium hover:bg-surface-2"
          >
            Open simulator
          </Link>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          How it works
        </h2>
        <ol className="grid gap-3 sm:grid-cols-2">
          {STEPS.map((step, i) => (
            <li key={step.title} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-mono text-xs text-muted">0{i + 1}</p>
              <p className="mt-1 font-medium">{step.title}</p>
              <p className="mt-1 text-sm text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Quick start</h2>
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>
            Open{" "}
            <Link className="text-accent underline" href="/compare">
              Compare
            </Link>
            . The defaults run a sinusoidal workload against all three strategies.
          </li>
          <li>
            Change the pattern to <em>Sudden spike</em> and raise the provisioning delay to 120 s.
          </li>
          <li>Run it again and see how each strategy handles the spike in latency and cost.</li>
        </ol>
        <p className="text-sm text-muted">The same comparison from the command line:</p>
        <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-4 font-mono text-xs">
          {`curl -s localhost:8000/simulations/compare \\
  -H 'content-type: application/json' \\
  -d '{"scenario": {"workload": {"pattern": "spike"}}}' | jq '.results[].summary.latency'`}
        </pre>
      </section>

      <section className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
        <p className="font-medium text-fg">Scope</p>
        <p className="mt-1">
          This is a simplified queueing model meant for comparing control policies. It does not
          model network latency, heterogeneous instances, failures or any specific provider&apos;s
          billing. Use the results to compare policies, not to predict production capacity.
        </p>
      </section>
    </div>
  );
}
