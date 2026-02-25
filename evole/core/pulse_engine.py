"""
Pulse Engine -- Micro-Burst PWM Atomizer Control.

Translates intensity and ratio values from the BlendDial into a timed
pulse schedule that drives the two pump GPIO pins.

Design principles:
  - Burst-based (not long-spray): prevents surface wetness / droplets
  - Intensity = more pulses, not longer pulses -> preserves aerosol quality
  - Rate-limited: max N high-intensity bursts per 60 s (anti-saturate / bag-fire guard)
  - Temperature-aware: maximum pulse length scales inversely with ambient temp
    (alcohol flashpoint risk rises as atomised vapour concentration rises)
  - Soft-start/stop inherited from SoftRamp applied to burst envelope

Pulse timing reference (from user specification):
  Low Intensity  : 100 ms ON / 900 ms OFF   (subtle waft)
  High Intensity : 400 ms ON / 100 ms OFF   (dense projection)
  Micro-burst    :  50 ms ON /  30 ms OFF   (within each intensity burst)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Pulse schedule data types
# ---------------------------------------------------------------------------

@dataclass
class Pulse:
    """A single ON/OFF event for one pump channel."""
    on_ms: float
    off_ms: float
    channel: int = 0    # 0 = Vial A, 1 = Vial B


@dataclass
class PulseSchedule:
    """Complete ordered sequence of pulses for one fire event."""
    pulses: list[Pulse] = field(default_factory=list)

    @property
    def total_duration_ms(self) -> float:
        return sum(p.on_ms + p.off_ms for p in self.pulses)


# ---------------------------------------------------------------------------
# Intensity -> timing table
# ---------------------------------------------------------------------------

# Maps intensity grade (1-10) to (on_ms, off_ms, pulse_count)
# Low end: long gaps, few pulses. High end: short gaps, many rapid pulses.
_INTENSITY_TABLE: dict[int, tuple[float, float, int]] = {
    1:  (50.0,  900.0, 1),
    2:  (50.0,  700.0, 1),
    3:  (75.0,  500.0, 2),
    4:  (100.0, 400.0, 2),
    5:  (150.0, 300.0, 3),
    6:  (200.0, 200.0, 3),
    7:  (250.0, 150.0, 4),
    8:  (300.0, 120.0, 5),
    9:  (350.0, 100.0, 5),
    10: (400.0, 100.0, 6),
}

# Internal micro-burst breakdown: each "pulse" in the table is subdivided
MICRO_BURST_ON_MS = 50.0
MICRO_BURST_OFF_MS = 30.0


# ---------------------------------------------------------------------------
# Temperature-based max pulse cap
# ---------------------------------------------------------------------------

def _max_on_ms_for_temp(temp_celsius: float) -> float:
    """
    Scale maximum single-pulse ON time inversely with ambient temperature.
    Hotter ambient -> shorter max burst to limit vapour concentration.

    At 20 C (reference): no cap (400 ms allowed).
    At 40 C: cap at 200 ms.
    At 10 C: cap at 500 ms (cold reduces evaporation risk).
    """
    ref_temp = 20.0
    ref_max = 400.0
    scale = 1.0 - (temp_celsius - ref_temp) * 0.01   # -1 % per degree above 20
    capped = ref_max * scale
    return max(50.0, min(600.0, capped))


# ---------------------------------------------------------------------------
# Rate limiter (bag-fire / saturation guard)
# ---------------------------------------------------------------------------

class BurstRateLimiter:
    """
    Prevents more than max_high_bursts high-intensity events within window_s.
    High-intensity is defined as intensity >= threshold.
    """

    def __init__(
        self,
        max_high_bursts: int = 3,
        window_s: float = 60.0,
        high_threshold: int = 7,
    ) -> None:
        self._max = max_high_bursts
        self._window = window_s
        self._threshold = high_threshold
        self._event_times: list[float] = []

    def is_allowed(self, intensity: int) -> bool:
        if intensity < self._threshold:
            return True
        now = time.time()
        # Evict old events outside window
        self._event_times = [t for t in self._event_times if now - t < self._window]
        return len(self._event_times) < self._max

    def record_event(self, intensity: int) -> None:
        if intensity >= self._threshold:
            self._event_times.append(time.time())


# ---------------------------------------------------------------------------
# Core Pulse Engine
# ---------------------------------------------------------------------------

class PulseEngine:
    """
    Generates and manages timed pulse schedules for dual-vial atomization.

    Usage per fire event:
        schedule = engine.build_schedule(intensity, ratio_a, ratio_b, temp_c)
        for pulse in schedule.pulses:
            gpio_a.on() if pulse.channel == 0 else gpio_b.on()
            sleep_ms(pulse.on_ms)
            gpio_off()
            sleep_ms(pulse.off_ms)

    The engine is stateless between fire events (safe to call from ISR context).
    Rate limiting state is maintained internally.
    """

    def __init__(self, rate_limiter: Optional[BurstRateLimiter] = None) -> None:
        self._limiter = rate_limiter or BurstRateLimiter()

    def build_schedule(
        self,
        intensity: int,
        ratio_a: float,
        ratio_b: float,
        temp_celsius: float = 20.0,
    ) -> PulseSchedule:
        """
        Build an interleaved pulse schedule for both vials.

        Args:
            intensity:    1-10 grade from BlendDial or SceneManager.
            ratio_a:      Vial A contribution 0.0-100.0 %.
            ratio_b:      Vial B contribution 0.0-100.0 %.
            temp_celsius: Ambient temperature for flashpoint cap.

        Returns:
            PulseSchedule with interleaved A and B pulses.
        """
        intensity = max(1, min(10, intensity))

        if not self._limiter.is_allowed(intensity):
            # Rate limit hit: return empty schedule (silent fail)
            return PulseSchedule()

        on_ms, off_ms, pulse_count = _INTENSITY_TABLE[intensity]
        max_on = _max_on_ms_for_temp(temp_celsius)
        on_ms = min(on_ms, max_on)

        # Scale on-time by ratio (0-100 %) for each vial
        on_ms_a = on_ms * ratio_a / 100.0
        on_ms_b = on_ms * ratio_b / 100.0

        pulses: list[Pulse] = []
        for i in range(pulse_count):
            # Interleave A and B within each burst, with micro-gap between
            if on_ms_a >= MICRO_BURST_ON_MS:
                pulses.append(Pulse(on_ms=on_ms_a, off_ms=MICRO_BURST_OFF_MS, channel=0))
            if on_ms_b >= MICRO_BURST_ON_MS:
                pulses.append(Pulse(on_ms=on_ms_b, off_ms=off_ms, channel=1))
            elif on_ms_a >= MICRO_BURST_ON_MS:
                # Adjust last A pulse to carry full off-time if B is silent
                if pulses:
                    last = pulses[-1]
                    pulses[-1] = Pulse(on_ms=last.on_ms, off_ms=off_ms, channel=last.channel)

        self._limiter.record_event(intensity)
        return PulseSchedule(pulses=pulses)

    def micro_burst_sequence(self, count: int = 3, channel: int = 0) -> PulseSchedule:
        """
        Utility for prime/maintenance micro-burst sequences.
        Sub-perceptual: 50 ms pulses.
        """
        pulses = [
            Pulse(on_ms=MICRO_BURST_ON_MS, off_ms=MICRO_BURST_OFF_MS * 10, channel=channel)
            for _ in range(count)
        ]
        return PulseSchedule(pulses=pulses)
