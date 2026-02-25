"""Unit tests for BlendDial and pure mapping functions."""

import pytest
from evole.core.blend_dial import (
    BlendDial,
    DialMode,
    VialConfig,
    _adc_to_blend,
    _blend_to_intensity,
    execute_scent,
)


class TestAdcToBlend:
    def test_hard_left_stop(self):
        assert _adc_to_blend(0) == 0
        assert _adc_to_blend(50) == 0       # edge of dead zone

    def test_hard_right_stop(self):
        assert _adc_to_blend(1023) == 100
        assert _adc_to_blend(973) == 100    # edge of dead zone

    def test_centre(self):
        mid_adc = (50 + 973) // 2          # ~511
        result = _adc_to_blend(mid_adc)
        assert 48 <= result <= 52           # approximately 50

    def test_monotonic(self):
        prev = -1
        for adc in range(0, 1024, 32):
            blend = _adc_to_blend(adc)
            assert blend >= prev
            prev = blend


class TestBlendToIntensity:
    def test_centre_is_minimum(self):
        # blend=50 -> intensity floor
        assert _blend_to_intensity(50) == 2

    def test_hard_stops_are_max(self):
        assert _blend_to_intensity(0) == 10
        assert _blend_to_intensity(100) == 10

    def test_floor_at_2(self):
        # Near centre: 45-55 all floor at 2
        for b in range(45, 56):
            assert _blend_to_intensity(b) >= 2

    def test_v_curve_symmetric(self):
        assert _blend_to_intensity(20) == _blend_to_intensity(80)
        assert _blend_to_intensity(10) == _blend_to_intensity(90)


class TestBlendDial:
    def test_boot_check_primes_filter(self):
        dial = BlendDial()
        state = dial.boot_check(raw_adc=512)
        assert abs(state.filtered_adc - 512.0) < 1.0

    def test_orientation_lock_zeroes_duty(self):
        dial = BlendDial()
        dial.boot_check(512)
        state = dial.update(raw_adc=512, accel_z=0.0)   # flat -> locked
        assert state.orientation_locked is True
        assert state.duty_a_pct == 0.0
        assert state.duty_b_pct == 0.0

    def test_upright_produces_nonzero_duty(self):
        dial = BlendDial()
        dial.boot_check(512)
        state = dial.update(raw_adc=512, accel_z=1.0)
        assert not state.orientation_locked
        # Centre blend should give duty to both channels
        total = state.duty_a_pct + state.duty_b_pct
        assert total > 0

    def test_left_stop_is_100pct_a(self):
        dial = BlendDial()
        dial.boot_check(0)
        state = dial.update(raw_adc=0, accel_z=1.0)
        assert state.is_left_stop
        assert state.ratio_a == 100.0
        assert state.ratio_b == 0.0

    def test_right_stop_is_100pct_b(self):
        dial = BlendDial()
        dial.boot_check(1023)
        state = dial.update(raw_adc=1023, accel_z=1.0)
        assert state.is_right_stop
        assert state.ratio_b == 100.0
        assert state.ratio_a == 0.0

    def test_potency_multiplier_caps_duty(self):
        vial_b = VialConfig(name="Heavy Oud", potency_multiplier=0.8)
        dial = BlendDial(vial_b=vial_b)
        dial.boot_check(1023)
        state = dial.update(raw_adc=1023, accel_z=1.0)
        assert state.duty_b_pct <= 80.0 + 0.1   # never exceeds multiplier cap

    def test_mode_toggle_on_button_press(self):
        dial = BlendDial()
        dial.boot_check(512)
        assert dial.mode == DialMode.RATIO
        dial.update(raw_adc=512, accel_z=1.0, button_pressed=True)
        assert dial.mode == DialMode.INTENSITY

    def test_hysteresis_suppresses_small_changes(self):
        dial = BlendDial()
        dial.boot_check(500)
        # Small jitter should not change ADC value
        state1 = dial.update(raw_adc=502, accel_z=1.0)
        state2 = dial.update(raw_adc=504, accel_z=1.0)
        # Filtered values should be very close (hysteresis held previous)
        assert abs(state1.filtered_adc - state2.filtered_adc) < 5


class TestExecuteScent:
    def test_left_stop_all_a(self):
        result = execute_scent(0)
        assert result["ratio_a"] == 100
        assert result["ratio_b"] == 0
        assert len(result["pump_b_schedule"]) == 0

    def test_right_stop_all_b(self):
        result = execute_scent(1023)
        assert result["ratio_b"] == 100
        assert result["ratio_a"] == 0

    def test_intensity_floor(self):
        result = execute_scent(512)
        assert result["intensity"] >= 2

    def test_pulse_count_matches_intensity(self):
        result = execute_scent(0)     # hard stop = intensity 10
        # pump_a should have exactly intensity pulses
        assert len(result["pump_a_schedule"]) == result["intensity"]
