"""
BLE (Bluetooth Low Energy) Connectivity Module.

Provides the wireless interface between the Evolé Base MCU and the companion
mobile app (iOS / Android).

Design goals:
  - Low-latency control (scene changes, Boost trigger) — characteristic writes
  - Low power: advertise at 100 ms interval, connect on demand, disconnect when idle
  - GATT service tree mirrors the physical subsystem architecture
  - Telemetry pushed via notifications (not polled) to keep BLE radio off between updates

GATT Service UUID: 0xEA10   ("EA" = Evolé Aroma, "10" = base unit)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# GATT characteristic registry
# ---------------------------------------------------------------------------

class CharUUID(str, Enum):
    """Short UUIDs (16-bit base expanded to 128-bit in firmware)."""
    # Read-only telemetry
    BATTERY_SOC         = "EA10:0001"
    TEMPERATURE_C       = "EA10:0002"
    AMPOULE_REMAINING   = "EA10:0003"
    ACTIVE_SCENT        = "EA10:0004"
    SYSTEM_STATE        = "EA10:0005"
    DUTY_CYCLE          = "EA10:0006"

    # Write-only control
    SCENE_SELECT        = "EA10:0101"
    INTENSITY_GRADE     = "EA10:0102"
    BOOST_TRIGGER       = "EA10:0103"
    POWER_OFF           = "EA10:0104"

    # Read-Write config
    SCHEDULE_CONFIG     = "EA10:0201"
    DEVICE_NAME         = "EA10:0202"

    # Notification / Indicate
    ALERT_NOTIFY        = "EA10:0301"   # low-battery, empty-ampoule, fault


class AlertCode(Enum):
    LOW_BATTERY     = 0x01
    CRITICAL_BATTERY = 0x02
    AMPOULE_LOW     = 0x10
    AMPOULE_EMPTY   = 0x11
    AMPOULE_AUTH_FAIL = 0x12
    DRIVER_FAULT    = 0x20
    THERMAL_FAULT   = 0x21
    SESSION_START   = 0x30
    SESSION_END     = 0x31
    BOOST_FIRED     = 0x40


# ---------------------------------------------------------------------------
# Packet encode/decode helpers
# ---------------------------------------------------------------------------

def encode_telemetry_packet(
    soc_pct: float,
    temp_c: float,
    remaining_ul: float,
    duty_pct: float,
    system_state_id: int,
) -> bytes:
    """
    Pack telemetry into a compact 13-byte notification payload.

      Byte  0     : system_state_id (uint8)
      Bytes 1–2   : battery SOC × 10 (uint16, e.g. 995 = 99.5 %)
      Bytes 3–4   : temperature × 10 signed (int16, e.g. 215 = 21.5 °C)
      Bytes 5–8   : remaining_ul (float32)
      Bytes 9–10  : duty_pct × 10 (uint16)
    """
    return struct.pack(
        ">BHhfH",
        system_state_id & 0xFF,
        int(soc_pct * 10) & 0xFFFF,
        int(temp_c * 10),
        remaining_ul,
        int(duty_pct * 10) & 0xFFFF,
    )


def decode_intensity_grade_write(payload: bytes) -> int:
    """Extract intensity grade (1–10) from a 1-byte GATT write."""
    if len(payload) < 1:
        raise ValueError("Empty intensity grade payload")
    grade = payload[0]
    return max(1, min(10, grade))


def decode_scene_select_write(payload: bytes) -> int:
    """Extract scene type index from a 1-byte GATT write."""
    if len(payload) < 1:
        raise ValueError("Empty scene select payload")
    return payload[0]


def encode_alert(code: AlertCode, detail_byte: int = 0) -> bytes:
    """2-byte alert notification: [alert_code, detail]."""
    return bytes([code.value & 0xFF, detail_byte & 0xFF])


# ---------------------------------------------------------------------------
# BLE peripheral state machine
# ---------------------------------------------------------------------------

class BLEState(Enum):
    OFF = auto()
    ADVERTISING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()


@dataclass
class BLEConfig:
    device_name: str = "Evole-Base"
    adv_interval_ms: int = 100          # 100 ms → fast enough for app discovery
    connection_timeout_s: float = 30.0  # auto-disconnect after 30 s of inactivity
    notify_interval_s: float = 2.0      # telemetry push rate while connected


class BLEPeripheral:
    """
    Simulated BLE GATT peripheral.

    In production firmware this class maps to the SoftDevice / NimBLE / Zephyr
    BLE stack API calls.  Here it provides a clean interface for the MCU Core
    to publish data and receive commands without knowing the BLE stack details.

    Usage pattern:
        ble = BLEPeripheral(config, on_scene=..., on_grade=..., on_boost=...)
        ble.start_advertising()
        # In tick loop:
        if ble.is_connected:
            ble.push_telemetry(...)
        ble.process_pending_writes()
    """

    def __init__(
        self,
        config: Optional[BLEConfig] = None,
        on_scene_select: Optional[Callable[[int], None]] = None,
        on_intensity_grade: Optional[Callable[[int], None]] = None,
        on_boost_trigger: Optional[Callable[[], None]] = None,
        on_power_off: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config or BLEConfig()
        self._state = BLEState.OFF
        self._pending_writes: list[tuple[CharUUID, bytes]] = []
        self._pending_alerts: list[bytes] = []
        self._notify_elapsed: float = 0.0

        # Command callbacks
        self._on_scene_select = on_scene_select
        self._on_intensity_grade = on_intensity_grade
        self._on_boost_trigger = on_boost_trigger
        self._on_power_off = on_power_off

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_advertising(self) -> None:
        self._state = BLEState.ADVERTISING

    def stop(self) -> None:
        self._state = BLEState.OFF

    # Simulated connection events (in production: driven by stack callbacks)
    def _on_connect(self) -> None:
        self._state = BLEState.CONNECTED
        self._notify_elapsed = 0.0

    def _on_disconnect(self) -> None:
        self._state = BLEState.ADVERTISING  # auto re-advertise

    # ------------------------------------------------------------------
    # Outbound: telemetry notifications
    # ------------------------------------------------------------------

    def push_telemetry(
        self,
        soc_pct: float,
        temp_c: float,
        remaining_ul: float,
        duty_pct: float,
        system_state_id: int,
        dt: float,
    ) -> bool:
        """
        Encode and (rate-limited) push telemetry to the connected central.
        Returns True if a notification was emitted this tick.
        """
        if self._state != BLEState.CONNECTED:
            return False

        self._notify_elapsed += dt
        if self._notify_elapsed < self.config.notify_interval_s:
            return False

        self._notify_elapsed = 0.0
        _ = encode_telemetry_packet(soc_pct, temp_c, remaining_ul, duty_pct, system_state_id)
        # In production: stack.notify(CharUUID.SYSTEM_STATE, packet)
        return True

    def send_alert(self, code: AlertCode, detail: int = 0) -> None:
        """Queue an alert notification for the connected central."""
        pkt = encode_alert(code, detail)
        self._pending_alerts.append(pkt)
        # In production: stack.indicate(CharUUID.ALERT_NOTIFY, pkt)

    # ------------------------------------------------------------------
    # Inbound: GATT write processing
    # ------------------------------------------------------------------

    def receive_write(self, char_uuid: CharUUID, payload: bytes) -> None:
        """Called by BLE stack on characteristic write from central."""
        self._pending_writes.append((char_uuid, payload))

    def process_pending_writes(self) -> None:
        """Drain write queue and dispatch to MCU callbacks (call from main loop)."""
        while self._pending_writes:
            uuid, payload = self._pending_writes.pop(0)

            if uuid == CharUUID.SCENE_SELECT and self._on_scene_select:
                self._on_scene_select(decode_scene_select_write(payload))

            elif uuid == CharUUID.INTENSITY_GRADE and self._on_intensity_grade:
                self._on_intensity_grade(decode_intensity_grade_write(payload))

            elif uuid == CharUUID.BOOST_TRIGGER and self._on_boost_trigger:
                self._on_boost_trigger()

            elif uuid == CharUUID.POWER_OFF and self._on_power_off:
                self._on_power_off()

    @property
    def is_connected(self) -> bool:
        return self._state == BLEState.CONNECTED

    @property
    def is_advertising(self) -> bool:
        return self._state == BLEState.ADVERTISING

    @property
    def state(self) -> BLEState:
        return self._state
