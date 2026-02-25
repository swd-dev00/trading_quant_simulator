"""
Charge + Power Management subsystem.

Handles:
  - Magnetic dock detection and power handoff
  - Hidden USB-C fallback charging path
  - Battery state tracking (SOC, health)
  - Regulated rail output to MCU and peripherals
"""

from dataclasses import dataclass, field
from enum import Enum, auto


class ChargeSource(Enum):
    NONE = auto()
    MAGNETIC_DOCK = auto()
    USB_C = auto()


class BatteryState(Enum):
    DISCHARGING = auto()
    CHARGING = auto()
    FULL = auto()
    FAULT = auto()


@dataclass
class PowerStatus:
    source: ChargeSource = ChargeSource.NONE
    battery_state: BatteryState = BatteryState.DISCHARGING
    soc_percent: float = 100.0          # State of charge 0–100
    voltage_mv: float = 3700.0          # Cell voltage in millivolts
    charging_current_ma: float = 0.0
    rail_3v3_ok: bool = True
    rail_5v_ok: bool = True


class PowerManager:
    """
    Controls charge source arbitration, battery monitoring, and power rail supervision.

    Dock priority: Magnetic dock (Qi-adjacent inductive pad) takes priority.
    USB-C acts as a hidden fallback for bench/travel charging.
    """

    # Thresholds
    LOW_BATTERY_THRESHOLD_PCT = 15.0
    CRITICAL_BATTERY_THRESHOLD_PCT = 5.0
    FULL_CHARGE_VOLTAGE_MV = 4200.0
    NOMINAL_VOLTAGE_MV = 3700.0
    CUTOFF_VOLTAGE_MV = 3000.0

    def __init__(self) -> None:
        self.status = PowerStatus()
        self._dock_present: bool = False
        self._usbc_present: bool = False

    # ------------------------------------------------------------------
    # Source detection (called by dock GPIO interrupt or USB VBUS detect)
    # ------------------------------------------------------------------

    def on_dock_connect(self) -> None:
        self._dock_present = True
        self._arbitrate()

    def on_dock_disconnect(self) -> None:
        self._dock_present = False
        self._arbitrate()

    def on_usbc_connect(self) -> None:
        self._usbc_present = True
        self._arbitrate()

    def on_usbc_disconnect(self) -> None:
        self._usbc_present = False
        self._arbitrate()

    def _arbitrate(self) -> None:
        """Select highest-priority available charge source."""
        if self._dock_present:
            self.status.source = ChargeSource.MAGNETIC_DOCK
            self.status.battery_state = BatteryState.CHARGING
            self.status.charging_current_ma = 500.0   # 0.5 C for a 1000 mAh cell
        elif self._usbc_present:
            self.status.source = ChargeSource.USB_C
            self.status.battery_state = BatteryState.CHARGING
            self.status.charging_current_ma = 1000.0  # USB-C 5 V / 2 A path
        else:
            self.status.source = ChargeSource.NONE
            self.status.battery_state = BatteryState.DISCHARGING
            self.status.charging_current_ma = 0.0

    # ------------------------------------------------------------------
    # Periodic update (call from MCU main loop, e.g. every 10 s)
    # ------------------------------------------------------------------

    def update(self, measured_voltage_mv: float, measured_current_ma: float) -> PowerStatus:
        self.status.voltage_mv = measured_voltage_mv
        soc = self._voltage_to_soc(measured_voltage_mv)
        self.status.soc_percent = soc

        if measured_voltage_mv >= self.FULL_CHARGE_VOLTAGE_MV and self.status.battery_state == BatteryState.CHARGING:
            self.status.battery_state = BatteryState.FULL
            self.status.charging_current_ma = 0.0

        if measured_voltage_mv < self.CUTOFF_VOLTAGE_MV:
            self.status.battery_state = BatteryState.FAULT

        return self.status

    def _voltage_to_soc(self, mv: float) -> float:
        """Linear approximation between cutoff and full-charge voltage."""
        span = self.FULL_CHARGE_VOLTAGE_MV - self.CUTOFF_VOLTAGE_MV
        soc = (mv - self.CUTOFF_VOLTAGE_MV) / span * 100.0
        return max(0.0, min(100.0, soc))

    @property
    def is_low_battery(self) -> bool:
        return self.status.soc_percent < self.LOW_BATTERY_THRESHOLD_PCT

    @property
    def is_critical_battery(self) -> bool:
        return self.status.soc_percent < self.CRITICAL_BATTERY_THRESHOLD_PCT
