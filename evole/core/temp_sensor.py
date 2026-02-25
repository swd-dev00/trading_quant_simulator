"""
Ambient Temperature Sensor subsystem.

Feeds into the MCU Intelligent Core for:
  - Atomization duty-cycle compensation (fragrance volatility is temperature-dependent)
  - Thermal runaway protection (halt atomization if enclosure overheats)
  - Diffusion rate modelling (higher ambient temp → lower duty cycle needed)

Sensor target: NTC thermistor or low-cost I²C sensor (e.g. TMP112, SHT31).
"""

from dataclasses import dataclass
import math


@dataclass
class ThermalReading:
    celsius: float
    fahrenheit: float
    is_fault: bool = False


class TemperatureSensor:
    """
    Reads ambient temperature and exposes compensation factors for the
    atomization driver.

    Fragrance volatility model (simplified Clausius–Clapeyron-inspired):
      Relative evaporation rate ∝ exp(−ΔHvap / R·T)
    We approximate this as a piecewise linear correction table over the
    operating range 10 °C – 40 °C.
    """

    # Thermal protection limits
    MIN_OPERATING_CELSIUS = 0.0
    MAX_OPERATING_CELSIUS = 50.0
    ATOMISATION_HALT_CELSIUS = 55.0  # hard stop, possible electronics issue

    # Calibration reference: duty-cycle multiplier at each breakpoint
    # At 20 °C (nominal room temp) → multiplier = 1.0
    # Colder → higher duty cycle to compensate lower volatility
    # Warmer → lower duty cycle to avoid over-diffusion
    _BREAKPOINTS = [
        (10.0, 1.35),
        (15.0, 1.18),
        (20.0, 1.00),
        (25.0, 0.88),
        (30.0, 0.77),
        (35.0, 0.68),
        (40.0, 0.60),
    ]

    def __init__(self, i2c_address: int = 0x48) -> None:
        self.i2c_address = i2c_address
        self._last_reading = ThermalReading(celsius=20.0, fahrenheit=68.0)

    def read(self, raw_adc_counts: int, vref_mv: float = 3300.0) -> ThermalReading:
        """
        Convert raw ADC reading (NTC divider) to temperature.

        NTC Steinhart–Hart simplified (B-parameter method):
          1/T = 1/T0 + (1/B) * ln(R/R0)
        Constants for a typical 10 kΩ NTC with B = 3950 K.
        """
        R0 = 10_000.0   # Ohms at T0
        T0 = 298.15     # K (25 °C)
        B = 3950.0

        # Resistor divider: Rtop = 10 kΩ, ADC_MAX = 4095 (12-bit)
        adc_max = 4095
        if raw_adc_counts <= 0 or raw_adc_counts >= adc_max:
            self._last_reading = ThermalReading(celsius=20.0, fahrenheit=68.0, is_fault=True)
            return self._last_reading

        r_ntc = 10_000.0 * raw_adc_counts / (adc_max - raw_adc_counts)
        temp_k = 1.0 / (1.0 / T0 + math.log(r_ntc / R0) / B)
        temp_c = temp_k - 273.15
        temp_f = temp_c * 9.0 / 5.0 + 32.0

        self._last_reading = ThermalReading(celsius=round(temp_c, 2), fahrenheit=round(temp_f, 2))
        return self._last_reading

    def duty_cycle_multiplier(self) -> float:
        """
        Return the compensation multiplier for the atomization driver based on
        the last temperature reading.  Interpolates between breakpoints.
        """
        t = self._last_reading.celsius
        bp = self._BREAKPOINTS

        if t <= bp[0][0]:
            return bp[0][1]
        if t >= bp[-1][0]:
            return bp[-1][1]

        for i in range(len(bp) - 1):
            t0, m0 = bp[i]
            t1, m1 = bp[i + 1]
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0)
                return m0 + frac * (m1 - m0)

        return 1.0  # fallback

    @property
    def is_overheat(self) -> bool:
        return self._last_reading.celsius >= self.ATOMISATION_HALT_CELSIUS

    @property
    def last(self) -> ThermalReading:
        return self._last_reading
