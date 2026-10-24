"""Validated strategy configuration (discriminated on ``type``)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrategyBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str | None = Field(
        None, max_length=40, description="Optional display name; defaults to the strategy type"
    )


class FixedStrategyConfig(_StrategyBase):
    """Constant capacity baseline."""

    type: Literal["fixed"] = "fixed"
    replicas: int = Field(4, ge=1, le=1_000)


class ReactiveStrategyConfig(_StrategyBase):
    """Threshold-triggered, target-tracking utilisation autoscaler."""

    type: Literal["reactive"] = "reactive"
    upper_threshold: float = Field(0.75, gt=0, le=1, description="Scale up above this utilisation")
    lower_threshold: float = Field(
        0.35, ge=0, lt=1, description="Scale down below this utilisation"
    )
    target_utilisation: float = Field(0.6, gt=0, le=1, description="Utilisation to size towards")
    observation_window_s: float = Field(60.0, gt=0, le=3_600)
    scale_up_cooldown_s: float = Field(60.0, ge=0, le=3_600)
    scale_down_cooldown_s: float = Field(300.0, ge=0, le=7_200)
    max_step_up: int = Field(10, ge=1, le=1_000)
    max_step_down: int = Field(2, ge=1, le=1_000)
    backlog_drain_s: float = Field(
        30.0, gt=0, le=3_600, description="Target time to clear the current queue"
    )

    @model_validator(mode="after")
    def _ordered_thresholds(self) -> ReactiveStrategyConfig:
        if not self.lower_threshold < self.target_utilisation < self.upper_threshold:
            raise ValueError(
                "thresholds must satisfy lower_threshold < target_utilisation < upper_threshold "
                "(the gap between them is the hysteresis band)"
            )
        return self


class PredictiveStrategyConfig(_StrategyBase):
    """Holt (double exponential smoothing) forecast of arrival rate."""

    type: Literal["predictive"] = "predictive"
    alpha: float = Field(0.5, gt=0, le=1, description="Level smoothing factor")
    beta: float = Field(0.2, ge=0, le=1, description="Trend smoothing factor")
    horizon_s: float | None = Field(
        None,
        gt=0,
        le=3_600,
        description="Forecast horizon; defaults to provisioning delay + one control interval",
    )
    target_utilisation: float = Field(0.6, gt=0, le=1)
    lower_threshold: float = Field(
        0.35, ge=0, lt=1, description="Scale down only if forecast utilisation drops below this"
    )
    scale_up_cooldown_s: float = Field(30.0, ge=0, le=3_600)
    scale_down_cooldown_s: float = Field(300.0, ge=0, le=7_200)
    max_step_up: int = Field(10, ge=1, le=1_000)
    max_step_down: int = Field(2, ge=1, le=1_000)
    warmup_intervals: int = Field(4, ge=0, le=1_000)
    reactive_floor: bool = Field(
        True, description="Never provision below what the current observed demand requires"
    )
    backlog_drain_s: float = Field(30.0, gt=0, le=3_600)

    @model_validator(mode="after")
    def _ordered_thresholds(self) -> PredictiveStrategyConfig:
        if not self.lower_threshold < self.target_utilisation:
            raise ValueError("lower_threshold must be below target_utilisation")
        return self


StrategyConfig = Annotated[
    FixedStrategyConfig | ReactiveStrategyConfig | PredictiveStrategyConfig,
    Field(discriminator="type"),
]
