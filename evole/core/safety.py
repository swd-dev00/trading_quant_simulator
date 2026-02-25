"""
Invisible Safety Layer.

Proactive protection features that run silently in the background:

  1. Predictive Low-Juice Alerts  — pulse-count based remaining-volume estimation
                                    with early warning at 10 % threshold.
  2. Soft-Start / Soft-Stop       — 100–200 ms voltage ramp to eliminate the
                                    mechanical "click" and protect piezo mesh.
  3. Dry-Fire Guard               — halts atomizer if ampoule appears empty
                                    (back-pressure drop or pulse-count exhaustion).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Predictive Low-Juice Alert
# ---------------------------------------------------------------------------

@dataclass
class UsageEstimate:
    total_volume_ul: float
    remaining_volume_ul: float
    pulses_delivered: int
    ul_per_pulse: float

    @property
    def remaining_pct(self) -> float:
        if self.total_volume_ul <= 0:
            return 0.0
        return (self.remaining_volume_ul / self.total_volume_ul) * 100.0

    @property
    def is_low(self) -> bool:
        return self.remaining_pct <= 10.0

    @property
    def is_empty(self) -> bool:
        return self.remaining_volume_ul <= 0.0


class JuiceMonitor:
    """
    Estimates remaining fragrance volume from pulse count rather than waiting
    for a dry pump (which can burn the piezo mesh or heating element).

    Algorithm:
      - On NFC read: load total_volume_ul and remaining_volume_ul from tag.
      - Each atomizer ON-event (pulse): deduct estimated µL per pulse.
      - At 10 % remaining: emit LOW_JUICE alert to BLE / LED.
      - At 0 %: halt atomizer and emit EMPTY alert.

    µL-per-pulse is cartridge-specific (from ViscosityProfile) and can be
    refined by correlating pulse count vs. physical weighing during QA.
    """

    LOW_THRESHOLD_PCT = 10.0

    def __init__(self, total_ul: float, initial_remaining_ul: float, ul_per_pulse: float) -> None:
        self._total = total_ul
        self._remaining = initial_remaining_ul
        self._pulses = 0
        self._ul_per_pulse = ul_per_pulse
        self._alert_low_sent = False
        self._alert_empty_sent = False

    def record_pulse(self, count: int = 1) -> UsageEstimate:
        """Deduct volume for N pulses and return current estimate."""
        self._pulses += count
        self._remaining = max(0.0, self._remaining - count * self._ul_per_pulse)
        return self.estimate()

    def estimate(self) -> UsageEstimate:
        return UsageEstimate(
            total_volume_ul=self._total,
            remaining_volume_ul=self._remaining,
            pulses_delivered=self._pulses,
            ul_per_pulse=self._ul_per_pulse,
        )

    def consume_alert(self) -> Optional[str]:
        """
        Returns an alert string on state transitions (call once per tick).
        Returns None if no new alert.
        """
        est = self.estimate()
        if est.is_empty and not self._alert_empty_sent:
            self._alert_empty_sent = True
            return "EMPTY"
        if est.is_low and not self._alert_low_sent:
            self._alert_low_sent = True
            return "LOW_10PCT"
        return None

    def sync_from_nfc(self, remaining_ul: float) -> None:
        """Re-sync after NFC write-back (e.g. power cycle with tag present)."""
        self._remaining = remaining_ul
        self._alert_low_sent = remaining_ul / self._total * 100.0 <= self.LOW_THRESHOLD_PCT
        self._alert_empty_sent = remaining_ul <= 0.0


# ---------------------------------------------------------------------------
# 2. Soft-Start / Soft-Stop Ramp
# ---------------------------------------------------------------------------

@dataclass
class SoftRampConfig:
    ramp_duration_ms: float = 150.0   # 100–200 ms target per spec
    steps: int = 20                   # number of PWM increments in ramp


class SoftRamp:
    """
    Generates a smooth voltage ramp schedule for the atomizer gate driver.

    Instead of abrupt 0→duty or duty→0 transitions that produce a mechanical
    'click' (piezo ring-down or inductor snap), the MCU issues incremental
    PWM steps over 100–200 ms.

    generate_ramp_up() : 0 % → target duty, over ramp_duration_ms
    generate_ramp_down(): target duty → 0 %, over ramp_duration_ms

    Each element in the returned list is a (duty_pct, hold_ms) tuple that
    the MCU hardware timer should apply sequentially.
    """

    def __init__(self, config: Optional[SoftRampConfig] = None) -> None:
        self.config = config or SoftRampConfig()

    def generate_ramp_up(self, target_duty_pct: float) -> list[tuple[float, float]]:
        """Return list of (duty_pct, hold_ms) for a smooth start."""
        return self._ramp(0.0, target_duty_pct)

    def generate_ramp_down(self, from_duty_pct: float) -> list[tuple[float, float]]:
        """Return list of (duty_pct, hold_ms) for a smooth stop."""
        return self._ramp(from_duty_pct, 0.0)

    def _ramp(self, start: float, end: float) -> list[tuple[float, float]]:
        cfg = self.config
        hold_ms = cfg.ramp_duration_ms / cfg.steps
        result: list[tuple[float, float]] = []
        for i in range(cfg.steps + 1):
            t = i / cfg.steps
            # Ease-in-out cubic for perceptual smoothness
            t_eased = t * t * (3.0 - 2.0 * t)
            duty = start + (end - start) * t_eased
            result.append((round(duty, 2), hold_ms))
        return result


# ---------------------------------------------------------------------------
# 3. Dry-Fire Guard
# ---------------------------------------------------------------------------

class DryFireGuard:
    """
    Detects a likely empty ampoule from back-pressure anomaly or
    pulse-count exhaustion and halts the atomizer immediately.

    Two detection methods (use whichever sensor is available):
      A. Pulse-count exhaustion: JuiceMonitor reports is_empty.
      B. Back-pressure drop: the piezo drive current drops below a
         threshold when no liquid is present (mesh vibrating in air
         draws less current than when wetted).
    """

    # Method B threshold: current drop below this suggests dry mesh
    DRY_CURRENT_THRESHOLD_MA = 30.0   # calibrate per hardware revision

    def __init__(self) -> None:
        self._dry_fire_detected = False

    def check(
        self,
        juice_estimate: Optional[UsageEstimate],
        drive_current_ma: float,
    ) -> bool:
        """
        Return True if dry-fire condition detected.
        Caller should immediately halt atomizer on True.
        """
        # Method A: volume exhausted
        if juice_estimate is not None and juice_estimate.is_empty:
            self._dry_fire_detected = True
            return True

        # Method B: anomalously low drive current during active atomization
        if drive_current_ma < self.DRY_CURRENT_THRESHOLD_MA:
            self._dry_fire_detected = True
            return True

        return False

    def reset(self) -> None:
        self._dry_fire_detected = False

    @property
    def is_triggered(self) -> bool:
        return self._dry_fire_detected
