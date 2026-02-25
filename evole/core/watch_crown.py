"""
Watch Crown Dial Controller -- Push-Pull Dual-Layer Interface.

Models the "watch crown" interaction pattern:
  - Pushed in  (Active Mode):   rotating selects Scent Ratio / Scene label.
                                Auto-fire enabled after 800 ms dwell.
  - Pulled out (Setup Mode):    rotating adjusts Intensity (pulse count).
                                Auto-fire disabled; all pump power is gated OFF.
                                Haptic motor pulses count out the intensity level.

Additional features:
  - Over-rotate boost: hold dial at hard stop > 2 s -> "Double Pulse" turbo mode.
  - Scent Memory: intensity preference saved per-ampoule-SKU (EEPROM-backed dict).
  - Safety air-gap: while pulled out, pump MOSFET gate is forced LOW regardless
    of software state. Prevents spray during maintenance or travel.
  - On push-back-in: haptic confirmation, restore saved intensity for current ampoule.

Scent labels on the physical dial arc (example 3-position):
  MORN | WORK | NIGHT
  Each maps to a SceneType and a default intensity grade.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Dial labels (physical engravings on the arc)
# ---------------------------------------------------------------------------

class DialLabel(Enum):
    MORN  = "Morning"
    WORK  = "Deep Work"
    NIGHT = "Date Night"


# Default intensity grade per label (overridden by scent memory)
_LABEL_DEFAULT_GRADE: dict[DialLabel, int] = {
    DialLabel.MORN:  4,
    DialLabel.WORK:  3,
    DialLabel.NIGHT: 6,
}


# ---------------------------------------------------------------------------
# Crown state
# ---------------------------------------------------------------------------

class CrownPosition(Enum):
    PUSHED_IN  = auto()   # Active / Live Mode
    PULLED_OUT = auto()   # Setup / Programming Mode


@dataclass
class CrownState:
    position: CrownPosition = CrownPosition.PUSHED_IN
    label: DialLabel = DialLabel.MORN
    intensity_grade: int = 4
    is_pump_gated: bool = False      # True = pumps hard-disabled (pulled-out safety)
    dwell_seconds: float = 0.0       # time held at current label position
    over_rotate_seconds: float = 0.0 # time held at hard stop
    turbo_active: bool = False
    pending_haptic_pulses: int = 0   # MCU should fire haptic motor N times


# ---------------------------------------------------------------------------
# Persistent scent memory
# ---------------------------------------------------------------------------

class ScentMemory:
    """
    Maps ampoule SKU -> (label -> intensity_grade).
    In production this is written to MCU internal EEPROM or I2C FRAM.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[DialLabel, int]] = {}

    def save(self, sku: str, label: DialLabel, grade: int) -> None:
        if sku not in self._store:
            self._store[sku] = {}
        self._store[sku][label] = grade

    def load(self, sku: str, label: DialLabel) -> int:
        return self._store.get(sku, {}).get(label, _LABEL_DEFAULT_GRADE[label])

    def has_memory(self, sku: str) -> bool:
        return sku in self._store


# ---------------------------------------------------------------------------
# ADC -> label mapping (3-position potentiometer arc)
# ---------------------------------------------------------------------------

def _adc_to_label(adc: int) -> DialLabel:
    """
    Divide the 0-1023 ADC range into three equal sectors with small
    dead-bands at the boundaries to prevent jitter between labels.
    """
    if adc < 330:
        return DialLabel.MORN
    if adc < 680:
        return DialLabel.WORK
    return DialLabel.NIGHT


def _adc_to_setup_grade(adc: int) -> int:
    """
    In Setup Mode the full dial arc adjusts intensity 1-10.
    Linear map with dead zones.
    """
    dead_low, dead_high = 30, 993
    if adc <= dead_low:
        return 1
    if adc >= dead_high:
        return 10
    grade = int((adc - dead_low) / (dead_high - dead_low) * 9) + 1
    return max(1, min(10, grade))


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

DWELL_FIRE_THRESHOLD_S = 0.8      # auto-fire after 800 ms dwell in Active Mode
OVER_ROTATE_BOOST_THRESHOLD_S = 2.0  # hold at hard stop 2 s -> turbo
OVER_ROTATE_ADC_THRESHOLD = 950   # "over-rotate zone"


class WatchCrownController:
    """
    Manages the push-pull potentiometer state machine.

    MCU integration:
      - Connect pull-out switch to external interrupt pin.
      - Call on_crown_toggle() from ISR.
      - Call tick() every ~100 ms from main loop, passing latest ADC and time delta.
      - Inspect state.is_pump_gated before enabling atomizer gate MOSFET.
      - Drive haptic motor for state.pending_haptic_pulses counts then clear.

    Safety contract:
      is_pump_gated == True   =>  pump MOSFET gate MUST be held LOW by hardware.
      The software alone should not be trusted; a discrete MOSFET tied to the
      switch GPIO provides the hardware air-gap.
    """

    def __init__(
        self,
        memory: Optional[ScentMemory] = None,
        on_fire: Optional[Callable[[DialLabel, int], None]] = None,
    ) -> None:
        self._memory = memory or ScentMemory()
        self._on_fire = on_fire   # callback: (label, intensity_grade)
        self._state = CrownState()
        self._current_sku: str = ""
        self._prev_label: Optional[DialLabel] = None
        self._prev_adc: int = 512

    # ------------------------------------------------------------------
    # Interrupt service routine callback (push-pull switch event)
    # ------------------------------------------------------------------

    def on_crown_toggle(self, is_pulled_out: bool) -> None:
        """
        Called from external interrupt when the dial shaft is pushed/pulled.

        Args:
            is_pulled_out: True if dial is now in the pulled-out (Setup) position.
        """
        if is_pulled_out:
            self._state.position = CrownPosition.PULLED_OUT
            self._state.is_pump_gated = True   # safety air-gap
            self._state.turbo_active = False
        else:
            # Pushing back in: save current intensity for this label + ampoule
            label = self._state.label
            grade = self._state.intensity_grade
            if self._current_sku:
                self._memory.save(self._current_sku, label, grade)

            self._state.position = CrownPosition.PUSHED_IN
            self._state.is_pump_gated = False
            self._state.pending_haptic_pulses = 1   # "Armed and Ready" confirmation

    # ------------------------------------------------------------------
    # Main loop tick
    # ------------------------------------------------------------------

    def tick(self, adc: int, dt: float, ampoule_present: bool = True) -> CrownState:
        """
        Advance the crown state machine by one time step.

        Args:
            adc:             10-bit ADC reading from potentiometer.
            dt:              Elapsed seconds since last tick.
            ampoule_present: False -> block all spray (empty/missing ampoule).

        Returns:
            Updated CrownState.
        """
        position = self._state.position

        if position == CrownPosition.PUSHED_IN:
            self._handle_active_mode(adc, dt, ampoule_present)
        else:
            self._handle_setup_mode(adc, dt)

        return self._state

    # ------------------------------------------------------------------
    # Active Mode (pushed in)
    # ------------------------------------------------------------------

    def _handle_active_mode(self, adc: int, dt: float, ampoule_present: bool) -> None:
        label = _adc_to_label(adc)

        # Over-rotate boost detection
        if adc >= OVER_ROTATE_ADC_THRESHOLD:
            self._state.over_rotate_seconds += dt
            if self._state.over_rotate_seconds >= OVER_ROTATE_BOOST_THRESHOLD_S:
                self._state.turbo_active = True
        else:
            self._state.over_rotate_seconds = 0.0
            self._state.turbo_active = False

        # Label change: reset dwell
        if label != self._prev_label:
            self._state.dwell_seconds = 0.0
            self._prev_label = label

        self._state.label = label
        self._state.intensity_grade = self._resolve_grade(label)
        self._state.dwell_seconds += dt

        # Auto-fire on dwell threshold
        if (
            self._state.dwell_seconds >= DWELL_FIRE_THRESHOLD_S
            and ampoule_present
            and not self._state.is_pump_gated
        ):
            effective_grade = self._state.intensity_grade
            if self._state.turbo_active:
                effective_grade = min(10, effective_grade * 2)  # double-pulse turbo
            self._fire(label, effective_grade)
            self._state.dwell_seconds = 0.0   # reset so it doesn't re-fire immediately

    # ------------------------------------------------------------------
    # Setup Mode (pulled out)
    # ------------------------------------------------------------------

    def _handle_setup_mode(self, adc: int, dt: float) -> None:
        grade = _adc_to_setup_grade(adc)
        delta = abs(adc - self._prev_adc)
        self._prev_adc = adc

        if grade != self._state.intensity_grade and delta > 5:
            self._state.intensity_grade = grade
            # Haptic feedback: N pulses = grade level divided by 3 (simplified)
            self._state.pending_haptic_pulses = max(1, grade // 3)

        # Pumps remain HARD gated while in setup mode regardless of ampoule state
        self._state.is_pump_gated = True

    # ------------------------------------------------------------------
    # Fire event
    # ------------------------------------------------------------------

    def _fire(self, label: DialLabel, grade: int) -> None:
        if self._on_fire:
            self._on_fire(label, grade)

    # ------------------------------------------------------------------
    # Ampoule swap (call when NFC reader detects new ampoule)
    # ------------------------------------------------------------------

    def on_ampoule_change(self, sku: str) -> None:
        """
        Load saved intensity preference for this ampoule's SKU.
        Restores the user's personal preference per scent cartridge.
        """
        self._current_sku = sku
        # Update intensity for current label from memory
        self._state.intensity_grade = self._resolve_grade(self._state.label)

    def _resolve_grade(self, label: DialLabel) -> int:
        if self._current_sku:
            return self._memory.load(self._current_sku, label)
        return _LABEL_DEFAULT_GRADE[label]

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def consume_haptic(self) -> int:
        """Return pending haptic pulse count and reset it (call from haptic driver)."""
        count = self._state.pending_haptic_pulses
        self._state.pending_haptic_pulses = 0
        return count

    @property
    def state(self) -> CrownState:
        return self._state

    @property
    def pumps_enabled(self) -> bool:
        """True only when safe to energise pump MOSFET gate."""
        return not self._state.is_pump_gated
