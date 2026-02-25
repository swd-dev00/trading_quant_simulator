"""
MCU / Intelligent Core subsystem.

Central orchestrator that wires together all Evolé Base subsystems:

    [Power Mgmt] ──→ [MCU Core] ←── [Temp Sensor]
                          │
                     [Atomization Driver]
                          │
                    [Diffuser/Nozzle Module]
                          │
                  [Sealed Ampoule Interface]
                          │
                   [Fragrance Ampoule] ←──→ [NFC Reader/Antenna]

Responsibilities:
  - Main control loop (10 Hz default tick rate)
  - Session lifecycle: start → warmup → active → rest → (repeat)
  - Temperature-compensated duty cycle calculation
  - Power-aware operation (suspend atomisation when critically low)
  - Twist-ring + proximity event routing
  - NFC read on ampoule insertion, fill write-back on session end
  - Fault aggregation and safe-state handling
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .ampoule import AmpouleInterface, AmpouleState
from .atomization import AtomizationDriver, AtomizationMode
from .diffuser import DiffuserModule, IntensityPreset
from .nfc import NFCAuthError, NFCReader
from .power import PowerManager
from .temp_sensor import TemperatureSensor


class SystemState(Enum):
    BOOT = auto()
    IDLE = auto()              # powered, no active session
    SESSION_ACTIVE = auto()    # diffusing
    SESSION_REST = auto()      # mandatory off-period between sessions
    CHARGING = auto()          # on dock, display charging status
    LOW_BATTERY = auto()       # below threshold, warn and limit
    FAULT = auto()             # one or more subsystems in fault


@dataclass
class MCUConfig:
    tick_rate_hz: float = 10.0
    session_duration_s: float = 900.0    # overridden by ampoule NFC profile
    rest_duration_s: float = 900.0       # overridden by ampoule NFC profile
    manual_mode: bool = False            # True = twist ring governs duty directly


@dataclass
class SystemTelemetry:
    system_state: SystemState = SystemState.BOOT
    temp_celsius: float = 20.0
    battery_soc_pct: float = 100.0
    duty_cycle_pct: float = 0.0
    session_elapsed_s: float = 0.0
    rest_elapsed_s: float = 0.0
    ampoule_remaining_ul: float = 0.0
    active_scent: str = ""
    faults: list = field(default_factory=list)


class MCUCore:
    """
    Evolé Base Intelligent Core.

    Typical integration (hardware abstraction):
      - ADC channels: battery voltage, drive current, NTC thermistor, proximity
      - GPIO inputs: Hall sensor (ampoule seated), dock detect, USB-C VBUS
      - GPIO outputs: PWM to atomization MOSFET, status LED, solenoid eject
      - I²C/SPI: NFC reader IC, optional OLED/e-ink status display
    """

    def __init__(self, config: Optional[MCUConfig] = None) -> None:
        self.config = config or MCUConfig()
        self._tick_interval = 1.0 / self.config.tick_rate_hz

        # Subsystems
        self.power = PowerManager()
        self.temp = TemperatureSensor()
        self.nfc = NFCReader()
        self.driver = AtomizationDriver()
        self.diffuser = DiffuserModule()
        self.ampoule = AmpouleInterface(
            on_seated=self._on_ampoule_seated,
            on_ejected=self._on_ampoule_ejected,
        )

        self._state = SystemState.BOOT
        self._rest_elapsed: float = 0.0
        self._telemetry = SystemTelemetry()
        self._faults: list[str] = []

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self) -> None:
        """Run startup checks and transition to IDLE."""
        self._self_test()
        self._state = SystemState.IDLE

    def _self_test(self) -> None:
        """Minimal power-on self-test (POST)."""
        # In production: read rail voltages, verify NFC comms, verify ADC refs
        assert self.power.status.rail_3v3_ok, "3.3 V rail fault"
        assert self.power.status.rail_5v_ok,  "5 V rail fault"

    # ------------------------------------------------------------------
    # Main control loop tick
    # ------------------------------------------------------------------

    def tick(
        self,
        dt: float,
        adc_battery_mv: float,
        adc_current_ma: float,
        adc_ntc_counts: int,
        adc_proximity_cm: float,
    ) -> SystemTelemetry:
        """
        Advance all subsystems by one time step.

        Args:
            dt: Elapsed time since last tick (seconds).
            adc_battery_mv: Battery cell voltage from ADC.
            adc_current_ma: Atomizer drive current from sense resistor.
            adc_ntc_counts: Raw 12-bit ADC count from NTC divider.
            adc_proximity_cm: Distance from IR/capacitive proximity sensor.

        Returns:
            Up-to-date SystemTelemetry snapshot.
        """
        # 1. Power management
        pwr = self.power.update(adc_battery_mv, adc_current_ma)
        self._telemetry.battery_soc_pct = pwr.soc_percent

        # 2. Temperature sensing + compensation
        thermal = self.temp.read(adc_ntc_counts)
        self._telemetry.temp_celsius = thermal.celsius
        temp_mult = self.temp.duty_cycle_multiplier()

        # 3. Thermal overheat protection
        if self.temp.is_overheat:
            self._add_fault("thermal_overheat")
            self.driver.stop_session()
            self._state = SystemState.FAULT

        # 4. Critical battery protection
        if self.power.is_critical_battery and self._state == SystemState.SESSION_ACTIVE:
            self.driver.stop_session()
            self._state = SystemState.LOW_BATTERY

        # 5. Proximity trigger (only in IDLE / rest states)
        if self._state in (SystemState.IDLE, SystemState.SESSION_REST):
            proximity_trigger = self.diffuser.on_proximity_reading(adc_proximity_cm)
            if proximity_trigger and self.diffuser.state.intensity_preset != IntensityPreset.OFF:
                self._start_session()

        # 6. Session state machine
        if self._state == SystemState.SESSION_ACTIVE:
            profile_ceiling = 80.0
            if self.nfc.current_ampoule:
                profile_ceiling = self.nfc.current_ampoule.profile.max_duty_cycle_pct

            base_duty = self.diffuser.base_duty_cycle()
            effective = self.driver.set_target(base_duty, temp_mult, profile_ceiling)
            self.driver.tick(dt, adc_current_ma)
            self._telemetry.duty_cycle_pct = effective
            self._telemetry.session_elapsed_s = self.driver.state.session_elapsed_seconds

            session_limit = (
                self.nfc.current_ampoule.profile.session_duration_seconds
                if self.nfc.current_ampoule
                else self.config.session_duration_s
            )
            if self.driver.state.session_elapsed_seconds >= session_limit:
                self._end_session()

        elif self._state == SystemState.SESSION_REST:
            self._rest_elapsed += dt
            self._telemetry.rest_elapsed_s = self._rest_elapsed
            rest_limit = (
                self.nfc.current_ampoule.profile.rest_duration_seconds
                if self.nfc.current_ampoule
                else self.config.rest_duration_s
            )
            if self._rest_elapsed >= rest_limit:
                self._state = SystemState.IDLE
                self._rest_elapsed = 0.0

        elif self._state == SystemState.FAULT:
            # Safe state: driver already stopped above
            pass

        # 7. Driver fault propagation
        if self.driver.state.mode == AtomizationMode.FAULT:
            self._add_fault("driver_fault")
            self._state = SystemState.FAULT

        # 8. Telemetry snapshot
        self._telemetry.system_state = self._state
        self._telemetry.faults = list(self._faults)
        if self.nfc.current_ampoule:
            self._telemetry.active_scent = self.nfc.current_ampoule.scent_name
            self._telemetry.ampoule_remaining_ul = self.nfc.current_ampoule.remaining_volume_ul

        return self._telemetry

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _start_session(self) -> None:
        if not self.ampoule.is_ready:
            return
        if self.power.is_critical_battery:
            return
        self._state = SystemState.SESSION_ACTIVE
        self.driver.start_session()

    def _end_session(self) -> None:
        mean_duty = self._telemetry.duty_cycle_pct
        elapsed = self.driver.state.session_elapsed_seconds
        self.driver.stop_session()

        # Write fill level back to ampoule NFC tag
        if self.nfc.current_ampoule and elapsed > 0:
            self.nfc.deduct_volume(elapsed, mean_duty)

        self._state = SystemState.SESSION_REST
        self._rest_elapsed = 0.0

    # ------------------------------------------------------------------
    # Ampoule insertion/ejection callbacks
    # ------------------------------------------------------------------

    def _on_ampoule_seated(self) -> None:
        """Triggered by Hall sensor: read NFC tag."""
        # In production, raw_tag_bytes comes from NFC IC via I²C DMA buffer.
        # Caller must inject raw bytes; this stub signals readiness.
        pass  # NFC read initiated by external caller via read_ampoule_tag()

    def read_ampoule_tag(self, raw_tag_bytes: bytes) -> bool:
        """
        Trigger NFC read after ampoule is seated.
        Returns True if tag authenticated successfully.
        """
        try:
            self.nfc.read_ampoule(raw_tag_bytes)
            return True
        except NFCAuthError as e:
            self._add_fault(f"nfc_auth_fail: {e}")
            self.ampoule.signal_fault("nfc_auth")
            return False

    def _on_ampoule_ejected(self) -> None:
        if self._state == SystemState.SESSION_ACTIVE:
            self._end_session()
        self._state = SystemState.IDLE

    # ------------------------------------------------------------------
    # Manual twist-ring input (hardware encoder ISR → MCU handler)
    # ------------------------------------------------------------------

    def on_twist(self, angle_degrees: float) -> None:
        preset = self.diffuser.on_twist(angle_degrees)
        if preset == IntensityPreset.OFF:
            if self._state == SystemState.SESSION_ACTIVE:
                self._end_session()
        elif self._state == SystemState.IDLE and self.ampoule.is_ready:
            self._start_session()

    # ------------------------------------------------------------------
    # Fault management
    # ------------------------------------------------------------------

    def _add_fault(self, code: str) -> None:
        if code not in self._faults:
            self._faults.append(code)

    def clear_faults(self) -> None:
        self._faults.clear()
        self.driver.clear_fault()
        if self._state == SystemState.FAULT:
            self._state = SystemState.IDLE

    @property
    def telemetry(self) -> SystemTelemetry:
        return self._telemetry
