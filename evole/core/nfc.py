"""
NFC Reader/Antenna subsystem.

Reads the NFC tag embedded in each Fragrance Ampoule and surfaces:
  - Fragrance identity (SKU, scent family, concentration)
  - Ampoule fill level (written back by MCU after each session)
  - Authentication signature (anti-counterfeit, NDEF signed record)
  - Recommended diffusion profile (intensity curve, session duration)
  - Proximity-triggered settings (read when ampoule is inserted)

Target IC: ISO 15693 / NFC-V or NFC-A (e.g. ST25DV, NXP NTAG I²C Plus).
Communication to MCU: I²C or SPI bridge.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class ScentFamily(Enum):
    FLORAL = "floral"
    WOODY = "woody"
    CITRUS = "citrus"
    ORIENTAL = "oriental"
    FRESH = "fresh"
    GOURMAND = "gourmand"


@dataclass
class DiffusionProfile:
    """Recommended operating parameters encoded on the ampoule NFC tag."""
    base_intensity_pct: float = 40.0        # 0–100 %
    warmup_seconds: int = 5                 # ramp-up period
    session_duration_seconds: int = 900     # 15-minute default session
    rest_duration_seconds: int = 900        # mandatory off-period between sessions
    max_duty_cycle_pct: float = 80.0        # never exceed this regardless of temp comp


@dataclass
class AmpouleRecord:
    sku: str
    scent_name: str
    scent_family: ScentFamily
    concentration_pct: float               # e.g. 12.5 % fragrance oil in carrier
    fill_volume_ul: float                   # total fill in microlitres
    remaining_volume_ul: float             # updated by MCU after each session
    auth_signature: bytes                   # 16-byte HMAC-MD5 placeholder
    profile: DiffusionProfile = field(default_factory=DiffusionProfile)
    is_authentic: bool = False             # set after signature verification


class NFCAuthError(Exception):
    """Raised when an ampoule tag fails authentication."""


class NFCReader:
    """
    Manages ampoule NFC tag reads, authentication, and fill-level write-back.

    Authentication flow:
      1. Read UID + payload from tag.
      2. Recompute HMAC over (UID || SKU || fill_volume_ul) with shared device key.
      3. Compare against auth_signature stored in tag sector.
      4. Only allow diffusion if authentic.

    Fill write-back:
      After each session, estimated consumed volume (µL) is calculated from
      atomization time × flow rate and written back to the tag.
    """

    # Estimated micro-mesh atomizer flow rate at 100 % duty cycle
    FLOW_RATE_UL_PER_SEC = 0.08   # ~5 µL/min at full power

    # Shared device-class key (in production: per-device key from secure element)
    _DEVICE_CLASS_KEY = b"evole-auth-v1-key"

    def __init__(self) -> None:
        self._current: Optional[AmpouleRecord] = None

    # ------------------------------------------------------------------
    # Tag read (call on ampoule insertion event)
    # ------------------------------------------------------------------

    def read_ampoule(self, raw_tag_bytes: bytes) -> AmpouleRecord:
        """
        Parse raw NDEF/proprietary tag payload and authenticate.

        Tag layout (fixed-length binary, 64 bytes):
          Offset  Len  Field
               0    8  UID (device-unique, written at tag personalisation)
               8   16  SKU (ASCII, zero-padded)
              24   32  scent_name (ASCII, zero-padded)
              56    1  scent_family index
              57    4  concentration_pct (float32 big-endian)
              61    4  fill_volume_ul (float32 big-endian)
              65    4  remaining_volume_ul (float32 big-endian)
              69   16  auth_signature (HMAC-MD5 placeholder)
        Total: 85 bytes minimum
        """
        if len(raw_tag_bytes) < 85:
            raise ValueError(f"Tag payload too short: {len(raw_tag_bytes)} bytes")

        uid = raw_tag_bytes[0:8]
        sku = raw_tag_bytes[8:24].rstrip(b"\x00").decode("ascii")
        scent_name = raw_tag_bytes[24:56].rstrip(b"\x00").decode("ascii")
        family_idx = raw_tag_bytes[56]
        concentration = struct.unpack_from(">f", raw_tag_bytes, 57)[0]
        fill_vol = struct.unpack_from(">f", raw_tag_bytes, 61)[0]
        remaining_vol = struct.unpack_from(">f", raw_tag_bytes, 65)[0]
        signature = raw_tag_bytes[69:85]

        family = list(ScentFamily)[family_idx % len(ScentFamily)]

        record = AmpouleRecord(
            sku=sku,
            scent_name=scent_name,
            scent_family=family,
            concentration_pct=concentration,
            fill_volume_ul=fill_vol,
            remaining_volume_ul=remaining_vol,
            auth_signature=signature,
        )

        record.is_authentic = self._verify(uid, record)
        if not record.is_authentic:
            raise NFCAuthError(f"Ampoule '{sku}' failed authentication — possible counterfeit.")

        self._current = record
        return record

    def _verify(self, uid: bytes, record: AmpouleRecord) -> bool:
        payload = uid + record.sku.encode() + struct.pack(">f", record.fill_volume_ul)
        expected = hashlib.new("md5", self._DEVICE_CLASS_KEY + payload).digest()
        return expected == record.auth_signature

    # ------------------------------------------------------------------
    # Fill write-back (call after each diffusion session)
    # ------------------------------------------------------------------

    def deduct_volume(self, session_seconds: float, mean_duty_cycle_pct: float) -> float:
        """
        Estimate and deduct fragrance consumed during a session.
        Returns remaining volume in µL after deduction.
        """
        if self._current is None:
            raise RuntimeError("No ampoule loaded.")
        consumed = self.FLOW_RATE_UL_PER_SEC * session_seconds * (mean_duty_cycle_pct / 100.0)
        self._current.remaining_volume_ul = max(0.0, self._current.remaining_volume_ul - consumed)
        return self._current.remaining_volume_ul

    @property
    def current_ampoule(self) -> Optional[AmpouleRecord]:
        return self._current

    @property
    def is_empty(self) -> bool:
        if self._current is None:
            return True
        return self._current.remaining_volume_ul <= 0.0
