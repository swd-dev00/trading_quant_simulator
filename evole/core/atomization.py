"""
Atomization Driver subsystem.

Physically separate from the Diffuser/Nozzle Module — this is the electronics layer:
  MOSFET gate driver + PWM signal generation + overcurrent protection.

Responsibilities:
  - Accept a target duty cycle (0–100 %) from the MCU
  - Apply temperature compensation multiplier from TempSensor
  - Apply fragrance-profile ceiling from NFC record
  - Emit PWM signal to the piezo/mesh transducer or heating element
  - Monitor drive current for fault detection

Typical piezo mesh atomizer: 1.7 MHz ultrasonic, driven at 3.3 V or 5 V rail,
pull-down NMOS gate drive via MCU PWM GPIO.
"""

from dataclasses import dataclass
from enum import Enum, auto


class AtomizationMode(Enum):
    OFF = auto()
    STANDBY = auto()
    WARMUP = auto()
    ACTIVE = auto()
    FAULT = auto()


@dataclass
class DriverState:
    mode: AtomizationMode = AtomizationMode.OFF
    target_duty_pct: float = 0.0        # requested by MCU before compensation
    effective_duty_pct: float = 0.0     # after thermal + profile cap
    drive_current_ma: float = 0.0
    session_elapsed_seconds: float = 0.0
    is_overcurrent: bool = False


class AtomizationDriver:
    """
    PWM-based MOSFET gate driver for the piezo mesh atomizer.

    Signal chain:
      MCU GPIO (PWM, ~1 kHz envelope) → NMOS gate → piezo mesh transducer
      Sense resistor → ADC → overcurrent comparator feedback

    The driver is intentionally stateless regarding fragrance — it only knows
    about duty cycle, current limits, and thermal protection signals from the MCU.
    """

    # Hardware limits
    MAX_DUTY_CYCLE_PCT = 100.0
    MIN_DUTY_CYCLE_PCT = 0.0
    OVERCURRENT_THRESHOLD_MA = 250.0    # ~1 W at 5 V with 20 % headroom
    WARMUP_RAMP_RATE_PCT_PER_SEC = 10.0 # gentle ramp from 0 → target

    def __init__(self) -> None:
        self.state = DriverState()
        self._ramp_current_pct: float = 0.0

    # ------------------------------------------------------------------
    # Control interface (called by MCU core each control-loop tick)
    # ------------------------------------------------------------------

    def set_target(
        self,
        duty_pct: float,
        temp_multiplier: float = 1.0,
        profile_ceiling_pct: float = 80.0,
    ) -> float:
        """
        Set desired duty cycle and return the compensated effective value.

        Args:
            duty_pct: Requested intensity (0–100).
            temp_multiplier: From TempSensor.duty_cycle_multiplier().
            profile_ceiling_pct: Max allowed from ampoule DiffusionProfile.

        Returns:
            Effective duty cycle actually applied.
        """
        if self.state.mode == AtomizationMode.FAULT:
            return 0.0

        self.state.target_duty_pct = max(self.MIN_DUTY_CYCLE_PCT, min(self.MAX_DUTY_CYCLE_PCT, duty_pct))
        compensated = self.state.target_duty_pct * temp_multiplier
        effective = min(compensated, profile_ceiling_pct, self.MAX_DUTY_CYCLE_PCT)
        self.state.effective_duty_pct = max(self.MIN_DUTY_CYCLE_PCT, effective)
        return self.state.effective_duty_pct

    def tick(self, delta_seconds: float, measured_current_ma: float) -> DriverState:
        """
        Advance driver state machine by one control-loop tick.

        Args:
            delta_seconds: Time since last tick.
            measured_current_ma: ADC-measured drive current.

        Returns:
            Updated DriverState.
        """
        self.state.drive_current_ma = measured_current_ma

        # Overcurrent protection
        if measured_current_ma > self.OVERCURRENT_THRESHOLD_MA:
            self._fault("overcurrent")
            return self.state

        if self.state.mode == AtomizationMode.WARMUP:
            self._ramp_current_pct = min(
                self._ramp_current_pct + self.WARMUP_RAMP_RATE_PCT_PER_SEC * delta_seconds,
                self.state.effective_duty_pct,
            )
            if self._ramp_current_pct >= self.state.effective_duty_pct:
                self.state.mode = AtomizationMode.ACTIVE

        if self.state.mode == AtomizationMode.ACTIVE:
            self.state.session_elapsed_seconds += delta_seconds

        return self.state

    # ------------------------------------------------------------------
    # Mode transitions
    # ------------------------------------------------------------------

    def start_session(self) -> None:
        if self.state.mode in (AtomizationMode.OFF, AtomizationMode.STANDBY):
            self.state.mode = AtomizationMode.WARMUP
            self._ramp_current_pct = 0.0
            self.state.session_elapsed_seconds = 0.0

    def stop_session(self) -> None:
        self.state.mode = AtomizationMode.STANDBY
        self.state.effective_duty_pct = 0.0
        self._ramp_current_pct = 0.0

    def power_off(self) -> None:
        self.state.mode = AtomizationMode.OFF
        self.state.effective_duty_pct = 0.0
        self._ramp_current_pct = 0.0

    def clear_fault(self) -> None:
        """Manually reset after fault investigation."""
        self.state.is_overcurrent = False
        self.state.mode = AtomizationMode.OFF

    def _fault(self, reason: str) -> None:
        self.state.mode = AtomizationMode.FAULT
        self.state.effective_duty_pct = 0.0
        self.state.is_overcurrent = reason == "overcurrent"

    @property
    def pwm_duty(self) -> float:
        """Current PWM duty cycle to write to the hardware timer register (0.0–1.0)."""
        if self.state.mode == AtomizationMode.WARMUP:
            return self._ramp_current_pct / 100.0
        if self.state.mode == AtomizationMode.ACTIVE:
            return self.state.effective_duty_pct / 100.0
        return 0.0
