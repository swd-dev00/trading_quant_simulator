"""
Sealed Ampoule Interface subsystem.

Mechanical docking layer — treated as its own subsystem given the luxury
insertion UX requirement.

Covers:
  - Magnetic collar locking (spring-loaded bayonet with magnets to guide alignment)
  - Hermetically sealed micro-neck pierce/seal mechanism
  - UV-blocking outer vessel (prevents fragrance degradation from ambient light)
  - Ampoule presence detection (Hall-effect sensor on collar)
  - Insertion/ejection event signalling to MCU
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional


class AmpouleState(Enum):
    ABSENT = auto()         # no ampoule seated
    INSERTING = auto()      # mid-insertion, collar not yet locked
    SEATED = auto()         # magnetically locked, seal pierced, ready
    EJECTING = auto()       # release sequence initiated
    FAULT = auto()          # seal failure, misalignment, etc.


@dataclass
class AmpoulePhysicalSpec:
    """Geometric constants for the ampoule design."""
    outer_diameter_mm: float = 18.0       # slender cylinder for luxury proportions
    neck_diameter_mm: float = 3.2         # micro-neck, matched to piercer pin
    vessel_height_mm: float = 60.0        # tall-thin silhouette
    uv_filter_transmission_pct: float = 1.0  # <1 % UV-A/B transmission target
    collar_magnet_pull_n: float = 8.5     # N52 magnets, sufficient for IP54 seal retention


class AmpouleInterface:
    """
    Manages the sealed ampoule mechanical interface.

    Magnetic collar locking:
      Four N52 magnets in a radial pattern guide the ampoule into the correct
      angular orientation and generate audible/tactile 'click' at full seat.
      A Hall-effect sensor signals SEATED state to the MCU.

    Hermetic seal:
      A spring-loaded stainless piercer pin penetrates the ampoule silicone
      micro-stopper on insertion.  The elastomer re-seals on ejection (tested
      for ≥100 cycles without fragrance bleed).

    UV-blocking vessel:
      Borosilicate glass with vacuum-deposited UV-reflective coating (TiO₂/SiO₂
      multilayer).  Blocks >99 % of UV-A and UV-B while maintaining visual
      clarity for the luxury reveal.
    """

    def __init__(
        self,
        spec: Optional[AmpoulePhysicalSpec] = None,
        on_seated: Optional[Callable[[], None]] = None,
        on_ejected: Optional[Callable[[], None]] = None,
    ) -> None:
        self.spec = spec or AmpoulePhysicalSpec()
        self.state = AmpouleState.ABSENT
        self._on_seated = on_seated
        self._on_ejected = on_ejected
        self._hall_sensor_triggered: bool = False

    # ------------------------------------------------------------------
    # Sensor callbacks (wired to MCU GPIO interrupts)
    # ------------------------------------------------------------------

    def on_hall_sensor_high(self) -> None:
        """Hall-effect sensor fires when magnet alignment completes."""
        if self.state == AmpouleState.INSERTING:
            self.state = AmpouleState.SEATED
            if self._on_seated:
                self._on_seated()

    def on_hall_sensor_low(self) -> None:
        """Hall sensor clears — ampoule has left the collar."""
        if self.state in (AmpouleState.EJECTING, AmpouleState.SEATED):
            self.state = AmpouleState.ABSENT
            if self._on_ejected:
                self._on_ejected()

    # ------------------------------------------------------------------
    # Insertion / ejection sequence
    # ------------------------------------------------------------------

    def begin_insertion(self) -> None:
        """Called when the MCU detects initial ampoule approach (capacitive proximity or IR)."""
        if self.state == AmpouleState.ABSENT:
            self.state = AmpouleState.INSERTING

    def request_eject(self) -> bool:
        """
        Initiate ejection sequence.  The MCU drives a solenoid or shape-memory
        alloy actuator to partially lift the ampoule for user removal.

        Returns False if ejection is blocked (e.g. mid-session).
        """
        if self.state == AmpouleState.SEATED:
            self.state = AmpouleState.EJECTING
            return True
        return False

    def signal_fault(self, reason: str = "") -> None:
        self.state = AmpouleState.FAULT

    @property
    def is_ready(self) -> bool:
        """True when an ampoule is sealed and ready for atomization."""
        return self.state == AmpouleState.SEATED

    @property
    def current_state(self) -> AmpouleState:
        return self.state
