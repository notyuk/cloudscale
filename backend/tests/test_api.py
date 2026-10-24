"""Integration tests through the HTTP layer."""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SMALL_SCENARIO: dict[str, Any] = {
    "duration_s": 600,
    "seed": 7,
    "workload": {
        "pattern": "spike",
        "base_rate": 5,
        "spike_rate": 30,
        "spike_start_s": 200,
        "spike_duration_s": 120,
    },
    "cluster": {
        "slots_per_server": 4,
        "min_replicas": 1,
        "max_replicas": 10,
        "initial_replicas": 2,
        "provisioning_delay_s": 30,
    },
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(cors_origins=["http://localhost:3000"]), raise_server_exceptions=False
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_strategies_listing(client: TestClient) -> None:
    body = client.get("/strategies").json()
    assert [s["type"] for s in body] == ["fixed", "reactive", "predictive"]
    assert all("properties" in s["parameters_schema"] for s in body)


def test_defaults_are_runnable(client: TestClient) -> None:
    defaults = client.get("/config/defaults").json()
    assert set(defaults["workload_patterns"]) == {
        "constant",
        "poisson",
        "sinusoidal",
        "spike",
        "ramp",
        "bursty",
    }
    response = client.post(
        "/simulations/compare",
        json={
            "scenario": {**defaults["scenario"], "duration_s": 300},
            "strategies": defaults["strategies"],
        },
    )
    assert response.status_code == 200


def test_run_returns_versioned_result(client: TestClient) -> None:
    response = client.post(
        "/simulations/run", json={"scenario": SMALL_SCENARIO, "strategy": {"type": "reactive"}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["strategy"]["config"]["type"] == "reactive"
    summary = body["summary"]
    assert summary["requests_total"] == (
        summary["requests_completed"]
        + summary["requests_rejected"]
        + summary["requests_unfinished"]
    )
    ts = body["timeseries"]
    assert len(ts["t_start"]) == 40  # 600 s / 15 s buckets
    assert sum(ts["arrivals"]) == summary["requests_total"]


def test_compare_uses_identical_trace(client: TestClient) -> None:
    response = client.post(
        "/simulations/compare",
        json={
            "scenario": SMALL_SCENARIO,
            "strategies": [
                {"type": "fixed", "replicas": 3},
                {"type": "reactive"},
                {"type": "predictive", "label": "holt"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    labels = [r["strategy"]["label"] for r in body["results"]]
    assert labels == ["fixed (3)", "reactive", "holt"]
    arrivals = {tuple(r["timeseries"]["arrivals"]) for r in body["results"]}
    assert len(arrivals) == 1
    assert body["requests_generated"] == body["results"][0]["summary"]["requests_total"]


def test_results_are_deterministic_over_http(client: TestClient) -> None:
    payload = {"scenario": SMALL_SCENARIO, "strategy": {"type": "predictive"}}
    a = client.post("/simulations/run", json=payload).json()
    b = client.post("/simulations/run", json=payload).json()
    a.pop("runtime")
    b.pop("runtime")
    assert a == b


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"scenario": {"duration_s": -5}}, "duration_s"),
        ({"scenario": {"cluster": {"min_replicas": 5, "max_replicas": 2}}}, "cluster"),
        ({"strategy": {"type": "quantum"}}, "strategy"),
        ({"strategy": {"type": "reactive", "lower_threshold": 0.9}}, "strategy"),
        (
            {"scenario": {"workload": {"pattern": "sinusoidal", "base_rate": 1, "amplitude": 5}}},
            "workload",
        ),
        ({"unexpected": 1}, "unexpected"),
    ],
)
def test_validation_errors_are_structured(
    client: TestClient, payload: dict[str, Any], fragment: str
) -> None:
    response = client.post("/simulations/run", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert any(fragment in [str(p) for p in d["loc"]] for d in body["details"])
    assert "Traceback" not in response.text


def test_fixed_replicas_outside_bounds(client: TestClient) -> None:
    response = client.post(
        "/simulations/run",
        json={"scenario": SMALL_SCENARIO, "strategy": {"type": "fixed", "replicas": 50}},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_configuration"


def test_expensive_configuration_rejected_before_running(client: TestClient) -> None:
    response = client.post(
        "/simulations/run",
        json={
            "scenario": {
                "duration_s": 86_400,
                "metrics_interval_s": 60,
                "workload": {"pattern": "poisson", "rate": 1_000},
            }
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "limit_exceeded"


def test_too_many_strategies(client: TestClient) -> None:
    response = client.post("/simulations/compare", json={"strategies": [{"type": "fixed"}] * 6})
    assert response.status_code == 422


def test_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/simulations/run", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_body_size_limit() -> None:
    client = TestClient(create_app(max_body_bytes=100))
    response = client.post("/simulations/run", json={"scenario": SMALL_SCENARIO})
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_body_size_limit_without_content_length() -> None:
    client = TestClient(create_app(max_body_bytes=100))

    def chunks() -> Iterator[bytes]:
        yield b'{"scenario": {"duration_s": 60, '
        yield b" " * 200 + b"}}"

    response = client.post(
        "/simulations/run", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_internal_errors_hide_details(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal state")

    monkeypatch.setattr("app.api.routes.compare", boom)
    response = client.post("/simulations/run", json={})
    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert "secret" not in response.text


def test_busy_server_returns_503() -> None:
    app = create_app(max_concurrent=1, queue_timeout_s=0.01)
    app.state.simulation_semaphore.acquire()
    response = TestClient(app).post("/simulations/run", json={})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"


def test_cors_allows_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/simulations/run",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_openapi_documents_endpoints(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in [
        "/health",
        "/strategies",
        "/config/defaults",
        "/simulations/run",
        "/simulations/compare",
    ]:
        assert path in spec["paths"]


def test_simulation_core_does_not_import_web_framework() -> None:
    """Architectural guard: the engine must stay independent of FastAPI/HTTP."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for package in ["simulation", "strategies", "workloads", "metrics"]:
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert not name.startswith(("fastapi", "starlette", "app.api")), (
                        f"{path.name} imports {name}"
                    )


def test_short_extreme_spike_rejected_before_generation(client: TestClient) -> None:
    # Few expected requests, but thinning would draw peak_rate * duration candidates.
    scenario = {
        "duration_s": 86_400,
        "metrics_interval_s": 60,
        "workload": {
            "pattern": "spike",
            "base_rate": 0.1,
            "spike_rate": 5_000,
            "spike_start_s": 0,
            "spike_duration_s": 1,
        },
    }
    response = client.post("/simulations/run", json={"scenario": scenario})
    assert response.status_code == 422
    assert response.json()["error"] == "limit_exceeded"


@pytest.mark.parametrize(
    "scenario",
    [
        {"workload": {"pattern": "bursty", "mean_burst_s": 1e-6}},
        {"duration_s": 86_400, "metrics_interval_s": 60, "control_interval_s": 0.01},
    ],
)
def test_pathological_timing_rejected(client: TestClient, scenario: dict[str, Any]) -> None:
    response = client.post("/simulations/run", json={"scenario": scenario})
    assert response.status_code == 422


def test_nan_and_infinity_rejected(client: TestClient) -> None:
    # Python's json module accepts these literals, so they must be caught by validation.
    for literal in ["NaN", "Infinity"]:
        body = '{"scenario": {"duration_s": ' + literal + "}}"
        response = client.post(
            "/simulations/run", content=body, headers={"content-type": "application/json"}
        )
        assert response.status_code == 422, literal
