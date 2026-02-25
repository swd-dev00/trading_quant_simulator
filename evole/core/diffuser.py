"""
Diffuser/Nozzle Module subsystem.

Physical output stage — separate concern from the Atomization Driver electronics.
This module models:
  - Nozzle geometry and orientation (directional vs. omnidirectional)
  - Twist-ring (grinder-style) manual intensity adjustment
  - Proximity-triggered session start (capacitive or IR sense)
  - Aerosol plume characteristics (droplet size, throw distance)

The twist mechanism maps a physical rotation angle (0–270°) to an
intensity preset without requiring an app or BLE pairing.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class NozzleOrientation(Enum):
    UPWARD = "upward"           # default: mist rises vertically
    ANGLED_45 = "angled_45"     # 45° forward projection
    DIFFUSE = "diffuse"         # omnidirectional via porous mesh cap


class IntensityPreset(Enum):
    """
    Discrete twist-ring positions.
    Maps to base duty-cycle values before thermal compensation.
    """
    OFF = 0
    LOW = 1       # ~20 % duty cycle — subtle, background scenting
    MEDIUM = 2    # ~45 % — everyday room use
    HIGH = 3      # ~70 % — large space or strong preference
    BOOST = 4     # ~90 % — short burst mode, max 5 min continuous


PRESET_BASE_DUTY = {
    IntensityPreset.OFF: 0.0,
    IntensityPreset.LOW: 20.0,
    IntensityPreset.MEDIUM: 45.0,
    IntensityPreset.HIGH: 70.0,
    IntensityPreset.BOOST: 90.0,
}

# Twist ring: 270° total travel, divided into equal sectors
TWIST_SECTORS = len(IntensityPreset)
TWIST_DEGREES_PER_SECTOR = 270.0 / (TWIST_SECTORS - 1)  # OFF included


@dataclass
class DiffuserState:
    orientation: NozzleOrientation = NozzleOrientation.UPWARD
    intensity_preset: IntensityPreset = IntensityPreset.OFF
    twist_angle_degrees: float = 0.0    # 0 = OFF, 270 = BOOST
    proximity_triggered: bool = False
    droplet_size_um: float = 5.0        # target: 1–10 µm for inhalation-safe mist


class DiffuserModule:
    """
    Physical nozzle/output stage controller.

    Twist mechanism (grinder-style):
      A rotary encoder or potentiometer on the collar ring feeds angle data to
      the MCU.  The MCU maps angle → IntensityPreset → base duty cycle, which
      is then forwarded to the AtomizationDriver.

    Proximity sensing:
      An IR emitter/detector pair or capacitive sense pad detects when a hand
      is within ~15 cm.  MCU triggers a session-start or boost event.
    """

    PROXIMITY_THRESHOLD_CM = 15.0

    def __init__(self, orientation: NozzleOrientation = NozzleOrientation.UPWARD) -> None:
        self.state = DiffuserState(orientation=orientation)

    # ------------------------------------------------------------------
    # Twist ring input
    # ------------------------------------------------------------------

    def on_twist(self, angle_degrees: float) -> IntensityPreset:
        """
        Handle a new twist-ring angle reading.

        Args:
            angle_degrees: Raw angle from encoder, 0–270.

        Returns:
            Resolved IntensityPreset.
        """
        angle_degrees = max(0.0, min(270.0, angle_degrees))
        self.state.twist_angle_degrees = angle_degrees

        sector = round(angle_degrees / TWIST_DEGREES_PER_SECTOR)
        preset = IntensityPreset(min(sector, TWIST_SECTORS - 1))
        self.state.intensity_preset = preset
        return preset

    def base_duty_cycle(self) -> float:
        """Return the base duty cycle (%) for the current intensity preset."""
        return PRESET_BASE_DUTY[self.state.intensity_preset]

    # ------------------------------------------------------------------
    # Proximity sensing
    # ------------------------------------------------------------------

    def on_proximity_reading(self, distance_cm: float) -> bool:
        """
        Evaluate a proximity sensor reading.

        Returns True if a trigger event should be generated (rising edge only).
        """
        was_triggered = self.state.proximity_triggered
        now_triggered = distance_cm <= self.PROXIMITY_THRESHOLD_CM
        self.state.proximity_triggered = now_triggered

        # Rising-edge trigger only (don't re-fire while hand stays in range)
        return now_triggered and not was_triggered

    # ------------------------------------------------------------------
    # Nozzle configuration
    # ------------------------------------------------------------------

    def set_orientation(self, orientation: NozzleOrientation) -> None:
        self.state.orientation = orientation

    @property
    def is_active(self) -> bool:
        return self.state.intensity_preset != IntensityPreset.OFF
