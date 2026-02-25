"""
User-Centric Scene & Intensity System.

Replaces raw timer/percentage controls with humanised abstractions:

  1. Intensity Grades   — 1–10 scale → mapped to PWM duty cycles internally.
  2. Lifestyle Scenes   — grouped presets (Deep Work, Date Night, Gym Refresh…)
                          that set grade + schedule in one tap.
  3. Smart Boost        — one-time immediate spray without altering the schedule.
  4. Scent Events       — time-anchored triggers distinct from recurring schedules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import datetime


# ---------------------------------------------------------------------------
# 1. Intensity Grade system (1–10 → PWM duty %)
# ---------------------------------------------------------------------------

# Mapping: grade 1 = barely perceptible, 10 = full output
# Non-linear curve: lower grades are compressed for subtlety
_GRADE_TO_DUTY: dict[int, float] = {
    1:  8.0,
    2: 14.0,
    3: 22.0,
    4: 32.0,
    5: 43.0,
    6: 55.0,
    7: 65.0,
    8: 74.0,
    9: 84.0,
    10: 93.0,
}


def grade_to_duty_pct(grade: int) -> float:
    """
    Map a user-visible 1–10 intensity grade to a PWM duty cycle percentage.

    Args:
        grade: Integer 1–10 (clamped if out of range).

    Returns:
        Duty cycle in percent (0.0–100.0).
    """
    grade = max(1, min(10, grade))
    return _GRADE_TO_DUTY[grade]


def duty_pct_to_grade(duty_pct: float) -> int:
    """Reverse mapping: nearest grade for a given duty cycle."""
    best = min(_GRADE_TO_DUTY.items(), key=lambda kv: abs(kv[1] - duty_pct))
    return best[0]


# ---------------------------------------------------------------------------
# 2. Lifestyle Scenes
# ---------------------------------------------------------------------------

class SceneType(Enum):
    DEEP_WORK = auto()
    DATE_NIGHT = auto()
    GYM_REFRESH = auto()
    MORNING_RITUAL = auto()
    WIND_DOWN = auto()
    GUEST_MODE = auto()
    CUSTOM = auto()


@dataclass
class SceneConfig:
    """
    Complete scent experience definition for a lifestyle Scene.

    Fields
    ------
    scene_type      : Enum identifier
    intensity_grade : 1–10 visible to user
    session_s       : Active diffusion duration in seconds
    rest_s          : Mandatory rest between sessions
    schedule_times  : Optional list of (hour, minute) daily trigger times
    preferred_families: Preferred scent families (advisory, not enforced)
    notes           : Human-readable description shown in the app
    """
    scene_type: SceneType
    intensity_grade: int               # 1–10
    session_s: float                   # seconds active per trigger
    rest_s: float                      # seconds off between sessions
    schedule_times: list[tuple[int, int]] = field(default_factory=list)
    preferred_families: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def duty_pct(self) -> float:
        return grade_to_duty_pct(self.intensity_grade)


# Built-in factory scenes
BUILT_IN_SCENES: dict[SceneType, SceneConfig] = {
    SceneType.DEEP_WORK: SceneConfig(
        scene_type=SceneType.DEEP_WORK,
        intensity_grade=3,
        session_s=1800,    # 30-min diffusion
        rest_s=1800,
        schedule_times=[(9, 0), (13, 0)],
        preferred_families=["woody", "fresh"],
        notes="Subtle background scenting to aid focus. Low grade avoids sensory fatigue.",
    ),
    SceneType.DATE_NIGHT: SceneConfig(
        scene_type=SceneType.DATE_NIGHT,
        intensity_grade=6,
        session_s=600,
        rest_s=1200,
        schedule_times=[(19, 30)],
        preferred_families=["oriental", "floral"],
        notes="Moderate intensity for intimate atmosphere. Single evening trigger.",
    ),
    SceneType.GYM_REFRESH: SceneConfig(
        scene_type=SceneType.GYM_REFRESH,
        intensity_grade=8,
        session_s=300,
        rest_s=600,
        schedule_times=[(6, 30), (18, 0)],
        preferred_families=["fresh", "citrus"],
        notes="High-intensity short bursts to energise and neutralise odours.",
    ),
    SceneType.MORNING_RITUAL: SceneConfig(
        scene_type=SceneType.MORNING_RITUAL,
        intensity_grade=4,
        session_s=900,
        rest_s=3600,
        schedule_times=[(7, 0)],
        preferred_families=["citrus", "fresh"],
        notes="Gentle morning wake-up. Single daily trigger, medium-low grade.",
    ),
    SceneType.WIND_DOWN: SceneConfig(
        scene_type=SceneType.WIND_DOWN,
        intensity_grade=2,
        session_s=2700,    # 45-minute slow diffusion
        rest_s=7200,
        schedule_times=[(21, 30)],
        preferred_families=["floral", "gourmand"],
        notes="Ultra-low grade for pre-sleep relaxation. Long session, rare recurrence.",
    ),
    SceneType.GUEST_MODE: SceneConfig(
        scene_type=SceneType.GUEST_MODE,
        intensity_grade=5,
        session_s=900,
        rest_s=900,
        preferred_families=["floral", "fresh"],
        notes="Neutral, crowd-pleasing settings for shared spaces.",
    ),
}


class SceneManager:
    """
    Manages scene selection, scheduling, and active scene state.
    """

    def __init__(self) -> None:
        self._active_scene: Optional[SceneConfig] = None
        self._custom_scenes: dict[str, SceneConfig] = {}

    def activate_scene(self, scene_type: SceneType) -> SceneConfig:
        scene = BUILT_IN_SCENES.get(scene_type)
        if scene is None:
            raise ValueError(f"Unknown scene type: {scene_type}")
        self._active_scene = scene
        return scene

    def activate_custom(self, name: str, config: SceneConfig) -> None:
        self._custom_scenes[name] = config
        self._active_scene = config

    def is_scheduled_now(self) -> bool:
        """Check if any schedule_time for the active scene matches the current wall-clock minute."""
        if self._active_scene is None or not self._active_scene.schedule_times:
            return False
        now = datetime.datetime.now()
        return (now.hour, now.minute) in self._active_scene.schedule_times

    @property
    def active(self) -> Optional[SceneConfig]:
        return self._active_scene

    @property
    def active_duty_pct(self) -> float:
        return self._active_scene.duty_pct if self._active_scene else 0.0

    @property
    def active_grade(self) -> int:
        return self._active_scene.intensity_grade if self._active_scene else 0


# ---------------------------------------------------------------------------
# 3. Smart Boost
# ---------------------------------------------------------------------------

@dataclass
class BoostConfig:
    duration_s: float = 30.0          # short burst, not a full session
    grade: int = 9                     # near-maximum intensity
    cooldown_s: float = 300.0          # prevent double-tapping Boost


class BoostController:
    """
    One-time immediate spray that does not modify the active scene schedule.

    Boost is designed to feel responsive and luxurious:
      - Triggers instantly on button press / app tap
      - Runs for a fixed short duration
      - Enforces a cooldown to prevent nozzle flooding
    """

    import time as _time

    def __init__(self, config: Optional[BoostConfig] = None) -> None:
        self.config = config or BoostConfig()
        self._last_boost_epoch: float = 0.0
        self._boost_active: bool = False
        self._boost_elapsed: float = 0.0

    def request_boost(self) -> bool:
        """
        Attempt to trigger a Boost event.
        Returns True if granted, False if in cooldown.
        """
        import time
        now = time.time()
        if now - self._last_boost_epoch < self.config.cooldown_s:
            return False
        self._boost_active = True
        self._boost_elapsed = 0.0
        self._last_boost_epoch = now
        return True

    def tick(self, dt: float) -> bool:
        """Advance boost timer. Returns True while boost is still active."""
        if not self._boost_active:
            return False
        self._boost_elapsed += dt
        if self._boost_elapsed >= self.config.duration_s:
            self._boost_active = False
        return self._boost_active

    @property
    def is_active(self) -> bool:
        return self._boost_active

    @property
    def duty_pct(self) -> float:
        return grade_to_duty_pct(self.config.grade) if self._boost_active else 0.0

    @property
    def cooldown_remaining_s(self) -> float:
        import time
        elapsed = time.time() - self._last_boost_epoch
        return max(0.0, self.config.cooldown_s - elapsed)
