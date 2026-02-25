"""
Graceful Physicality — Microfluidic Health & Maintenance Logic.

Handles the invisible hygiene layer that makes the device feel premium and
reliable over its operational lifetime:

  1. Prime-and-Purge Routine  — clears air bubbles on first use or refill.
  2. Viscosity Compensation   — adjusts atomizer on-time per scent cartridge.
  3. Anti-Clogging Stealth Pulse — keeps mesh moist after >48 h idle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Prime-and-Purge Routine
# ---------------------------------------------------------------------------

@dataclass
class PrimePurgeConfig:
    """
    High-frequency PWM burst sequence to evacuate air from microfluidic lines.

    Pulse pattern: alternating HIGH/LOW bursts at ~1 kHz envelope with short
    off-gaps to let surface tension wick liquid into cleared voids.
    """
    burst_on_ms: float = 50.0      # each active pulse width
    burst_off_ms: float = 20.0     # inter-pulse gap
    num_bursts: int = 12           # total pulses in sequence
    purge_cycles: int = 3          # repeat sequence N times with longer pause
    inter_cycle_pause_ms: float = 500.0
    # Expected total duration: ~3 × (12 × 70 ms + 500 ms) = ~4 s


class PrimePurge:
    """
    Generates a PWM burst schedule to prime the atomizer nozzle.

    Usage (pseudo-hardware call):
        schedule = PrimePurge(config).generate_schedule()
        for (on_ms, off_ms) in schedule:
            gpio.pwm_on()
            sleep_ms(on_ms)
            gpio.pwm_off()
            sleep_ms(off_ms)

    Returns a list of (on_ms, off_ms) tuples ready for the MCU DMA timer.
    """

    def __init__(self, config: Optional[PrimePurgeConfig] = None) -> None:
        self.config = config or PrimePurgeConfig()

    def generate_schedule(self) -> list[tuple[float, float]]:
        """Return list of (on_ms, off_ms) tuples for the DMA PWM timer."""
        cfg = self.config
        schedule: list[tuple[float, float]] = []

        for cycle in range(cfg.purge_cycles):
            for burst in range(cfg.num_bursts):
                # Last burst in cycle gets an extended off-gap
                if burst == cfg.num_bursts - 1:
                    off_ms = cfg.inter_cycle_pause_ms
                else:
                    off_ms = cfg.burst_off_ms
                schedule.append((cfg.burst_on_ms, off_ms))

        return schedule

    @property
    def total_duration_ms(self) -> float:
        cfg = self.config
        per_cycle = cfg.num_bursts * (cfg.burst_on_ms + cfg.burst_off_ms) + cfg.inter_cycle_pause_ms
        return cfg.purge_cycles * per_cycle


# ---------------------------------------------------------------------------
# 2. Viscosity Compensation
# ---------------------------------------------------------------------------

@dataclass
class ViscosityProfile:
    """
    Per-cartridge calibration parameters.

    Stored on the NFC tag (DiffusionProfile can be extended to include these)
    and used to scale atomizer on-time so every cartridge delivers a
    consistent 0.1 mL dose regardless of oil/carrier density.
    """
    sku: str
    dynamic_viscosity_mpa_s: float      # mPa·s (water ≈ 1, typical fragrance oil 5–50)
    reference_on_time_ms: float = 100.0 # baseline on-time at reference viscosity
    reference_viscosity_mpa_s: float = 10.0


class ViscosityCompensator:
    """
    Adjusts pump on-time so output volume stays at the target dose
    despite variation in liquid viscosity between cartridges.

    Model: For a fixed pressure head and orifice, volumetric flow rate Q ∝ 1/µ
    (Hagen–Poiseuille).  So on-time scales linearly with µ to maintain Q·t = const.

        on_time_adjusted = on_time_reference × (µ_sample / µ_reference)
    """

    TARGET_DOSE_ML = 0.10  # design target per spray event

    def __init__(self, profile: ViscosityProfile) -> None:
        self.profile = profile

    def adjusted_on_time_ms(self) -> float:
        """Return compensated on-time (ms) for the loaded cartridge."""
        ratio = self.profile.dynamic_viscosity_mpa_s / self.profile.reference_viscosity_mpa_s
        return self.profile.reference_on_time_ms * ratio

    def duty_scale_factor(self) -> float:
        """
        Alternative: return a multiplicative scale for the PWM duty cycle
        when on-time is fixed by hardware (e.g. locked timer period).
        """
        return self.profile.dynamic_viscosity_mpa_s / self.profile.reference_viscosity_mpa_s


# ---------------------------------------------------------------------------
# 3. Anti-Clogging Stealth Pulse
# ---------------------------------------------------------------------------

@dataclass
class AntiClogConfig:
    idle_threshold_hours: float = 48.0     # trigger after this many idle hours
    stealth_on_ms: float = 8.0             # sub-perceptual pulse (< 10 ms → no mist)
    stealth_off_ms: float = 2000.0         # 2 s gap between stealth pulses
    stealth_pulse_count: int = 3           # three gentle nudges per maintenance cycle
    maintenance_interval_hours: float = 48.0


class AntiClogManager:
    """
    Schedules microscopic maintenance pulses to keep the piezoelectric mesh
    and nozzle capillaries moist when the device has been idle.

    Pulses are intentionally below the fragrance-release threshold:
      < 10 ms at low duty cycle → surface tension breaks and re-wets mesh
      without producing a detectable aerosol plume.

    The MCU tracks last-active timestamp in RTC-backed NVRAM so the idle
    counter survives power cycles.
    """

    def __init__(self, config: Optional[AntiClogConfig] = None) -> None:
        self.config = config or AntiClogConfig()
        self._last_active_epoch: float = time.time()
        self._last_maintenance_epoch: float = time.time()

    def record_activity(self) -> None:
        """Call at the end of every real diffusion session."""
        self._last_active_epoch = time.time()

    def is_maintenance_due(self) -> bool:
        """
        Returns True if the device has been idle long enough to risk clogging
        and a maintenance cycle has not run recently.
        """
        now = time.time()
        idle_hours = (now - self._last_active_epoch) / 3600.0
        maint_hours = (now - self._last_maintenance_epoch) / 3600.0

        return (
            idle_hours >= self.config.idle_threshold_hours
            and maint_hours >= self.config.maintenance_interval_hours
        )

    def generate_stealth_schedule(self) -> list[tuple[float, float]]:
        """
        Return list of (on_ms, off_ms) stealth pulse pairs.
        Sub-perceptual: total aerosol produced is below olfactory threshold.
        """
        cfg = self.config
        schedule = [
            (cfg.stealth_on_ms, cfg.stealth_off_ms)
            for _ in range(cfg.stealth_pulse_count)
        ]
        return schedule

    def record_maintenance(self) -> None:
        """Call after a stealth maintenance cycle completes."""
        self._last_maintenance_epoch = time.time()

    @property
    def idle_hours(self) -> float:
        return (time.time() - self._last_active_epoch) / 3600.0
