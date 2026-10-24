"""Exact behavioural tests of the event engine on hand-built traces."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.simulation.engine import EventKind, SimulationBudgetExceededError, SimulationEngine
from app.simulation.entities import (
    InvalidTransitionError,
    RequestState,
    Server,
    ServerState,
)
from app.workloads.config import PoissonWorkload
from app.workloads.generators import generate_trace
from tests.conftest import ScriptedStrategy, make_scenario, make_trace, run_engine

S = RequestState


def test_single_request_latency_equals_service_time() -> None:
    run = run_engine(make_scenario(), [1.0], [2.5])
    assert run.states.tolist() == [S.COMPLETED]
    assert run.start_times[0] == 1.0
    assert run.completion_times[0] == pytest.approx(3.5)


def test_server_speed_scales_service_time() -> None:
    run = run_engine(make_scenario(server_speed=4.0), [0.0], [2.0])
    assert run.completion_times[0] == pytest.approx(0.5)


def test_fifo_order_with_simultaneous_arrivals() -> None:
    run = run_engine(make_scenario(), [0.0, 0.0, 0.0], [1.0, 1.0, 1.0])
    assert run.start_times.tolist() == [0.0, 1.0, 2.0]
    assert run.completion_times.tolist() == [1.0, 2.0, 3.0]


def test_fifo_is_not_shortest_job_first() -> None:
    run = run_engine(make_scenario(), [0.0, 0.1, 0.2], [5.0, 3.0, 0.5])
    # Arrival order is service order regardless of job size.
    assert np.argsort(run.start_times).tolist() == [0, 1, 2]


def test_slot_capacity_is_respected() -> None:
    run = run_engine(make_scenario(slots_per_server=2), [0, 0, 0, 0], [1, 1, 1, 1])
    assert run.completion_times.tolist() == [1.0, 1.0, 2.0, 2.0]


def test_bin_packing_lets_scale_down_terminate_idle_servers() -> None:
    # Two jobs on a 3x2-slot cluster pack onto server 0, so servers 1 and 2 stay
    # idle and a scale-down to 1 terminates them without draining.
    scenario = make_scenario(slots_per_server=2, initial_replicas=3)
    strategy = ScriptedStrategy(initial=3, policy=lambda obs: 1)
    run = run_engine(scenario, [0.0, 0.0], [50.0, 50.0], strategy)
    event = run.scaling_events[0]
    assert (event.terminated, event.drained) == (2, 0)
    assert run.servers[0].state is ServerState.ACTIVE


def test_completion_frees_slot_for_simultaneous_arrival() -> None:
    # Completion at t=1 is processed before the arrival at t=1, so zero wait.
    run = run_engine(make_scenario(), [0.0, 1.0], [1.0, 1.0])
    assert run.start_times[1] == 1.0


def test_queue_backpressure_rejects_when_full() -> None:
    run = run_engine(make_scenario(max_pending=1), [0, 0, 0], [1, 1, 1])
    assert run.states.tolist() == [S.COMPLETED, S.COMPLETED, S.REJECTED]
    assert math.isnan(run.start_times[2])


def test_zero_queue_still_serves_when_slot_free() -> None:
    run = run_engine(make_scenario(max_pending=0), [0.0, 0.5, 2.0], [1, 1, 1])
    assert run.states.tolist() == [S.COMPLETED, S.REJECTED, S.COMPLETED]


def test_unfinished_requests_at_end() -> None:
    run = run_engine(make_scenario(duration_s=5.0), [0.0, 4.0, 4.5], [1.0, 10.0, 1.0])
    assert run.states.tolist() == [S.COMPLETED, S.UNFINISHED, S.UNFINISHED]
    assert run.start_times[1] == 4.0  # in service
    assert math.isnan(run.start_times[2])  # still queued


def test_completion_exactly_at_end_is_unfinished() -> None:
    run = run_engine(make_scenario(duration_s=10.0), [5.0], [5.0])
    assert run.states.tolist() == [S.UNFINISHED]


def test_provisioning_delay_and_queued_requests_wait_for_new_server() -> None:
    scenario = make_scenario(duration_s=100.0, provisioning_delay_s=30.0, initial_replicas=1)

    def policy(obs):  # type: ignore[no-untyped-def]
        return 2 if obs.time == 10.0 else obs.committed

    strategy = ScriptedStrategy(initial=1, policy=policy)
    run = run_engine(scenario, [11.0, 12.0], [100.0, 1.0], strategy)
    launched = run.servers[1]
    assert launched.launched_at == 10.0
    assert launched.ready_at == 40.0
    # Request 1 arrived at 12 while server 1 was booting and starts when it is ready.
    assert run.start_times[1] == 40.0
    assert run.completion_times[1] == 41.0


def test_scale_down_drains_busy_server_without_dropping_work() -> None:
    scenario = make_scenario(duration_s=100.0, initial_replicas=2)
    strategy = ScriptedStrategy(initial=2, policy=lambda obs: 1)
    # Server 0 runs request 0 until 30, server 1 runs request 1 until 15.
    run = run_engine(scenario, [0.0, 0.0], [30.0, 15.0], strategy)
    assert run.states.tolist() == [S.COMPLETED, S.COMPLETED]
    event = run.scaling_events[0]
    assert (event.time, event.from_replicas, event.to_replicas) == (10.0, 2, 1)
    assert event.drained == 1
    # Least-loaded tie broken by newest id: server 1 drains and terminates at 15.
    assert run.servers[1].terminated_at == 15.0
    assert run.servers[0].state is ServerState.ACTIVE


def test_draining_server_receives_no_new_work() -> None:
    scenario = make_scenario(duration_s=100.0, initial_replicas=2)
    strategy = ScriptedStrategy(initial=2, policy=lambda obs: 1)
    run = run_engine(scenario, [0.0, 0.0, 11.0], [30.0, 15.0, 1.0], strategy)
    # Request 2 must wait for server 0 (busy until 30) rather than use draining server 1.
    assert run.start_times[2] == 30.0


def test_idle_server_terminates_immediately_on_scale_down() -> None:
    scenario = make_scenario(duration_s=50.0, initial_replicas=3)
    run = run_engine(scenario, [], [], ScriptedStrategy(initial=3, policy=lambda obs: 1))
    assert [s.terminated_at for s in run.servers] == [None, 10.0, 10.0]
    assert run.scaling_events[0].terminated == 2


def test_scale_down_cancels_booting_servers_first() -> None:
    scenario = make_scenario(duration_s=100.0, provisioning_delay_s=50.0)
    decisions = {10.0: 3, 20.0: 2}
    strategy = ScriptedStrategy(
        initial=1, policy=lambda obs: decisions.get(obs.time, obs.committed)
    )
    run = run_engine(scenario, [], [], strategy)
    assert run.scaling_events[1].cancelled == 1
    cancelled = run.servers[2]
    assert cancelled.ready_at is None
    assert cancelled.terminated_at == 20.0
    assert run.servers[1].ready_at == 60.0


def test_scale_up_reuses_draining_server() -> None:
    scenario = make_scenario(duration_s=100.0, initial_replicas=2, provisioning_delay_s=60.0)
    decisions = {10.0: 1, 20.0: 2}
    strategy = ScriptedStrategy(
        initial=2, policy=lambda obs: decisions.get(obs.time, obs.committed)
    )
    run = run_engine(scenario, [0.0, 0.0], [50.0, 50.0], strategy)
    assert run.scaling_events[1].reactivated == 1
    assert run.scaling_events[1].launched == 0
    assert len(run.servers) == 2


def test_replica_bounds_are_enforced_by_engine() -> None:
    scenario = make_scenario(duration_s=40.0, min_replicas=2, max_replicas=4, initial_replicas=2)
    big = run_engine(scenario, [], [], ScriptedStrategy(initial=2, policy=lambda obs: 1_000))
    assert max(e.to_replicas for e in big.scaling_events) == 4
    small = run_engine(scenario, [], [], ScriptedStrategy(initial=2, policy=lambda obs: 0))
    assert small.scaling_events == []


def test_time_weighted_queue_integral() -> None:
    # One slot, two unit jobs at t=0: queue length is 1 during [0, 1).
    run = run_engine(make_scenario(duration_s=10.0), [0.0, 0.0], [1.0, 1.0])
    assert run.snapshots[-1].integrals.queue == pytest.approx(1.0)
    assert run.snapshots[-1].integrals.busy_slots == pytest.approx(2.0)


def test_paid_time_includes_booting_and_draining() -> None:
    scenario = make_scenario(duration_s=100.0, provisioning_delay_s=20.0)
    decisions = {10.0: 2}
    strategy = ScriptedStrategy(
        initial=1, policy=lambda obs: decisions.get(obs.time, obs.committed)
    )
    run = run_engine(scenario, [], [], strategy)
    # Server 0 for 100s + server 1 from t=10 (booting until 30) to 100.
    assert run.snapshots[-1].integrals.paid_servers == pytest.approx(190.0)
    # Capacity counts only serving slots: 100 + 70.
    assert run.snapshots[-1].integrals.capacity_slots == pytest.approx(170.0)


def test_observations_cover_only_the_past() -> None:
    scenario = make_scenario(duration_s=30.0)
    strategy = ScriptedStrategy(initial=1)
    run_engine(scenario, [1.0, 9.0, 10.0, 15.0], [0.5, 0.5, 0.5, 0.5], strategy)
    # Arrival at exactly t=10 is processed before the control tick at t=10.
    assert [o.arrivals for o in strategy.observations] == [3, 1]
    assert strategy.observations[0].service_time_estimate_s == pytest.approx(0.5)


def test_event_priorities_are_ordered() -> None:
    assert (
        EventKind.SAMPLE
        < EventKind.COMPLETION
        < EventKind.SERVER_READY
        < EventKind.ARRIVAL
        < EventKind.CONTROL
    )


def test_invalid_server_transition_raises() -> None:
    server = Server(id=0, state=ServerState.TERMINATED, launched_at=0.0)
    with pytest.raises(InvalidTransitionError):
        server.transition(ServerState.ACTIVE)


def test_request_cannot_complete_twice() -> None:
    scenario = make_scenario()
    engine = SimulationEngine(scenario, make_trace([0.0], [1.0], 100.0), ScriptedStrategy(1))
    engine.run()
    with pytest.raises(InvalidTransitionError):
        engine._set_request_state(0, RequestState.COMPLETED)


def test_trace_duration_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="duration"):
        SimulationEngine(make_scenario(50.0), make_trace([], [], 100.0), ScriptedStrategy(1))


def test_wall_time_budget_aborts_long_runs() -> None:
    scenario = make_scenario(duration_s=2_000.0)
    trace = generate_trace(PoissonWorkload(rate=100), scenario.service, 2_000.0, seed=1)
    engine = SimulationEngine(scenario, trace, ScriptedStrategy(1), wall_time_budget_s=0.0)
    with pytest.raises(SimulationBudgetExceededError):
        engine.run()


def test_every_request_reaches_a_terminal_state() -> None:
    scenario = make_scenario(duration_s=20.0, max_pending=3)
    arrivals = np.linspace(0, 19.9, 60)
    run = run_engine(scenario, arrivals.tolist(), [1.0] * 60)
    terminal = {S.COMPLETED, S.REJECTED, S.UNFINISHED}
    assert set(run.states.tolist()) <= terminal
    assert (run.states == S.REJECTED).sum() > 0
