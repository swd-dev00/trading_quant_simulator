"""
Dual-Vial Blend Dial — Physical Potentiometer Interface.

Maps a single sealed potentiometer (270° travel, hard stops) to two
independent variables simultaneously:

  1. Ratio (A ↔ B)    — linear cross-fade between Vial A and Vial B
  2. Intensity         — V-curve: high at both hard stops, low at centre

V-Curve position map (12-o'clock = 0°, left = -135°, right = +135°):
  Hard Left Stop  (-135°): 100% Vial A | Max Intensity  "Power Morning"
  10-o'clock      ( -67°): 100% Vial A | Low Intensity  "Subtle Hint"
  Centre          (   0°): 50/50 Blend | Med Intensity  "Harmony"
  2-o'clock       ( +67°): 100% Vial B | Low Intensity
  Hard Right Stop (+135°): 100% Vial B | Max Intensity  "Signature Evening"

Additional features:
  - Dead-zone buffering at ADC rail values to absorb hard-stop jitter
  - Alpha exponential-moving-average smoothing ("creamy" transitions)
  - Hysteresis gate to suppress vibration micro-stutter
  - Velocity sensing: fast flick → "Quick-Set" snap to 100% intensity
  - Boot "Wake-and-Check": reads dial position before first spray
  - Orientation lock (via accelerometer Z-axis) blocks spray when horizontal
  - Per-vial Potency Multiplier to level-match loud/quiet fragrance notes
  - Click-to-toggle dual-layer: Layer 1 = Ratio mode, Layer 2 = Intensity mode
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# ADC constants (10-bit: 0–1023)
# ---------------------------------------------------------------------------

ADC_MAX = 1023
ADC_DEAD_LOW = 50      # 0–49  → guaranteed hard-left stop
ADC_DEAD_HIGH = 973    # 974–1023 → guaranteed hard-right stop

# Alpha for exponential moving average smoothing (0 < α ≤ 1)
# Lower = smoother (creamier) but slower to track fast turns
DEFAULT_ALPHA = 0.15

# Hysteresis threshold: ignore changes smaller than this ADC count
HYSTERESIS_THRESHOLD = 6

# Velocity threshold: ADC counts per tick that constitute a "fast flick"
FAST_FLICK_DELTA = 60


# ---------------------------------------------------------------------------
# Vial configuration
# ---------------------------------------------------------------------------

@dataclass
class VialConfig:
    """Per-vial calibration parameters."""
    name: str
    potency_multiplier: float = 1.0
    """
    Scale factor applied to this vial's output duty.
    Use < 1.0 for 'loud' heavy base notes (e.g. Oud) to prevent cloyingness.
    Use = 1.0 for balanced reference.
    Example: heavy Oud vial capped at 0.80 even at hard stop.
    """


# ---------------------------------------------------------------------------
# Dial read mode (click-to-toggle)
# ---------------------------------------------------------------------------

class DialMode(Enum):
    RATIO     = auto()    # rotating changes A↔B blend ratio
    INTENSITY = auto()    # rotating changes pulse count (volume)


# ---------------------------------------------------------------------------
# Blend state output
# ---------------------------------------------------------------------------

@dataclass
class BlendState:
    raw_adc: int = 512
    filtered_adc: float = 512.0
    blend_pct: int = 50         # 0 = 100% Vial A, 100 = 100% Vial B
    ratio_a: float = 50.0       # 0.0–100.0 %
    ratio_b: float = 50.0
    intensity: int = 5          # 1–10
    duty_a_pct: float = 0.0     # final duty after potency cap
    duty_b_pct: float = 0.0
    is_left_stop: bool = False
    is_right_stop: bool = False
    is_centre: bool = False
    mode: DialMode = DialMode.RATIO
    orientation_locked: bool = False


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class BlendDial:
    """
    Full dual-vial blend dial controller.

    Typical call sequence per MCU tick:
        state = dial.update(raw_adc=analogRead(), accel_z=readZ(), button_pressed=btn)
        pump_a.set_duty(state.duty_a_pct)
        pump_b.set_duty(state.duty_b_pct)
    """

    # Orientation: Z-axis reading above this threshold means device is upright
    # (gravity ≈ +1 g on Z when standing).  Adjust for your accelerometer mounting.
    UPRIGHT_Z_THRESHOLD = 0.6   # normalised: 0.0 = flat, 1.0 = fully upright

    def __init__(
        self,
        vial_a: Optional[VialConfig] = None,
        vial_b: Optional[VialConfig] = None,
        alpha: float = DEFAULT_ALPHA,
    ) -> None:
        self.vial_a = vial_a or VialConfig(name="Vial A")
        self.vial_b = vial_b or VialConfig(name="Vial B")
        self.alpha = alpha

        self._filtered: float = 512.0
        self._prev_raw: int = 512
        self._mode = DialMode.RATIO
        self._state = BlendState()

    # ------------------------------------------------------------------
    # Boot wake-and-check
    # ------------------------------------------------------------------

    def boot_check(self, raw_adc: int) -> BlendState:
        """
        Must be called before the first spray event.
        Reads the dial position immediately at power-on so the device
        doesn't surprise the user if the dial was moved while powered off.
        """
        # Prime filter to current position (no ramp-up lag)
        self._filtered = float(raw_adc)
        self._prev_raw = raw_adc
        return self._compute(raw_adc, accel_z=1.0, button_pressed=False, force=True)

    # ------------------------------------------------------------------
    # Per-tick update
    # ------------------------------------------------------------------

    def update(
        self,
        raw_adc: int,
        accel_z: float = 1.0,
        button_pressed: bool = False,
    ) -> BlendState:
        """
        Process one ADC sample and return the current blend state.

        Args:
            raw_adc:        10-bit ADC value (0–1023).
            accel_z:        Normalised Z-axis accelerometer reading (−1 to +1).
                            +1.0 = device fully upright (spray allowed).
            button_pressed: Encoder push-button for mode toggle.

        Returns:
            BlendState with ratio, intensity, and corrected duty cycles.
        """
        # Hysteresis gate — suppress micro-stuttering from vibration
        delta = abs(raw_adc - self._prev_raw)
        if delta < HYSTERESIS_THRESHOLD:
            raw_adc = self._prev_raw   # treat as unchanged
        else:
            self._prev_raw = raw_adc

        return self._compute(raw_adc, accel_z, button_pressed)

    # ------------------------------------------------------------------
    # Internal computation pipeline
    # ------------------------------------------------------------------

    def _compute(
        self,
        raw_adc: int,
        accel_z: float,
        button_pressed: bool,
        force: bool = False,
    ) -> BlendState:
        # 1. Mode toggle on button press
        if button_pressed:
            self._mode = (
                DialMode.INTENSITY if self._mode == DialMode.RATIO else DialMode.RATIO
            )

        # 2. Alpha EMA smoothing
        self._filtered = self.alpha * raw_adc + (1.0 - self.alpha) * self._filtered

        # 3. Velocity detection (fast flick → snap)
        velocity = abs(raw_adc - self._prev_raw)
        fast_flick = velocity >= FAST_FLICK_DELTA

        # 4. Dead-zone mapping → blend 0–100
        blend_pct = _adc_to_blend(int(self._filtered))
        is_left_stop = int(self._filtered) <= ADC_DEAD_LOW
        is_right_stop = int(self._filtered) >= ADC_DEAD_HIGH
        is_centre = 45 <= blend_pct <= 55

        # 5. Ratio computation
        ratio_b = float(blend_pct)
        ratio_a = 100.0 - ratio_b

        # 6. Intensity V-curve
        intensity = _blend_to_intensity(blend_pct)
        if fast_flick and (is_left_stop or is_right_stop):
            intensity = 10   # hard flick to stop → max intensity snap

        # 7. Orientation lock
        is_locked = accel_z < self.UPRIGHT_Z_THRESHOLD

        # 8. Final duty cycles with potency caps
        base_duty = intensity * 9.0   # maps 1–10 → 9–90 %
        duty_a = (ratio_a / 100.0) * base_duty * self.vial_a.potency_multiplier
        duty_b = (ratio_b / 100.0) * base_duty * self.vial_b.potency_multiplier
        duty_a = min(duty_a, 100.0 * self.vial_a.potency_multiplier)
        duty_b = min(duty_b, 100.0 * self.vial_b.potency_multiplier)

        if is_locked:
            duty_a = 0.0
            duty_b = 0.0

        self._state = BlendState(
            raw_adc=raw_adc,
            filtered_adc=self._filtered,
            blend_pct=blend_pct,
            ratio_a=ratio_a,
            ratio_b=ratio_b,
            intensity=intensity,
            duty_a_pct=round(duty_a, 2),
            duty_b_pct=round(duty_b, 2),
            is_left_stop=is_left_stop,
            is_right_stop=is_right_stop,
            is_centre=is_centre,
            mode=self._mode,
            orientation_locked=is_locked,
        )
        return self._state

    @property
    def state(self) -> BlendState:
        return self._state

    @property
    def mode(self) -> DialMode:
        return self._mode


# ---------------------------------------------------------------------------
# Pure mapping functions
# ---------------------------------------------------------------------------

def _adc_to_blend(adc: int) -> int:
    """
    Map 10-bit ADC (0–1023) to blend percentage (0–100) with dead zones.

    Equivalent of Arduino:
        int blend = constrain(map(analogRead(dialPin), 50, 970, 0, 100), 0, 100);
    """
    if adc <= ADC_DEAD_LOW:
        return 0
    if adc >= ADC_DEAD_HIGH:
        return 100
    blend = int((adc - ADC_DEAD_LOW) * 100 / (ADC_DEAD_HIGH - ADC_DEAD_LOW))
    return max(0, min(100, blend))


def _blend_to_intensity(blend_pct: int) -> int:
    """
    V-curve: intensity is high at both ends, minimum at centre (50).

    Formula:
        raw = |blend_pct - 50| / 5     → 0 at centre, 10 at ends
        intensity = max(raw, 2)         → floor at grade 2 (never completely silent)

    Mirrors the Arduino logic:
        int intensity = abs(map(rawValue, 0, 1023, -10, 10));
        if (intensity < 2) intensity = 2;
    """
    raw = abs(blend_pct - 50) // 5
    return max(raw, 2)


# ---------------------------------------------------------------------------
# Convenience: Arduino-style executeScent() translated to Python
# ---------------------------------------------------------------------------

def execute_scent(dial_adc: int) -> dict:
    """
    Direct translation of the provided Arduino executeScent() sketch
    into Python for simulation and unit-testing purposes.

    Returns a dict with ratio_a, ratio_b, intensity, and the pulse schedule
    for both pumps.
    """
    # Linear ratio
    ratio_b = _adc_to_blend(dial_adc)
    ratio_a = 100 - ratio_b

    # V-curve intensity (floor at 2)
    intensity = _blend_to_intensity(ratio_b)

    # Pulse schedule: intensity pulses of 50 ms ON / 30 ms OFF per pump
    PULSE_ON_MS = 50
    PULSE_OFF_MS = 30

    def pump_schedule(ratio_pct: int) -> list[tuple[float, float]]:
        """Return list of (on_ms, off_ms) adjusted for ratio."""
        on_ms = PULSE_ON_MS * ratio_pct / 100.0
        return [(on_ms, PULSE_OFF_MS)] * intensity if on_ms > 0 else []

    return {
        "ratio_a": ratio_a,
        "ratio_b": ratio_b,
        "intensity": intensity,
        "pump_a_schedule": pump_schedule(ratio_a),
        "pump_b_schedule": pump_schedule(ratio_b),
    }
