"""Unit tests for the Safety layer."""

import pytest
from evole.core.safety import (
    DryFireGuard,
    JuiceMonitor,
    SoftRamp,
    SoftRampConfig,
    UsageEstimate,
)


class TestJuiceMonitor:
    def test_initial_remaining(self):
        mon = JuiceMonitor(total_ul=2000.0, initial_remaining_ul=2000.0, ul_per_pulse=0.08)
        est = mon.estimate()
        assert est.remaining_pct == pytest.approx(100.0)

    def test_deduction_per_pulse(self):
        mon = JuiceMonitor(total_ul=1000.0, initial_remaining_ul=1000.0, ul_per_pulse=10.0)
        est = mon.record_pulse(5)
        assert est.remaining_volume_ul == pytest.approx(950.0)

    def test_low_alert_at_10pct(self):
        mon = JuiceMonitor(total_ul=100.0, initial_remaining_ul=11.0, ul_per_pulse=2.0)
        mon.record_pulse(1)   # drops to 9 ul -> 9%
        alert = mon.consume_alert()
        assert alert == "LOW_10PCT"

    def test_empty_alert(self):
        mon = JuiceMonitor(total_ul=10.0, initial_remaining_ul=2.0, ul_per_pulse=5.0)
        mon.record_pulse(1)   # drops to 0
        alert = mon.consume_alert()
        assert alert in ("EMPTY", "LOW_10PCT")   # may trigger both in sequence

    def test_alert_not_repeated(self):
        mon = JuiceMonitor(total_ul=100.0, initial_remaining_ul=5.0, ul_per_pulse=0.0)
        mon.record_pulse()
        mon.consume_alert()   # first call consumes it
        assert mon.consume_alert() is None

    def test_floor_at_zero(self):
        mon = JuiceMonitor(total_ul=10.0, initial_remaining_ul=5.0, ul_per_pulse=100.0)
        est = mon.record_pulse(1)
        assert est.remaining_volume_ul == 0.0


class TestSoftRamp:
    def test_ramp_starts_at_zero(self):
        ramp = SoftRamp()
        schedule = ramp.generate_ramp_up(target_duty_pct=80.0)
        assert schedule[0][0] == pytest.approx(0.0, abs=0.1)

    def test_ramp_ends_at_target(self):
        ramp = SoftRamp()
        schedule = ramp.generate_ramp_up(target_duty_pct=80.0)
        assert schedule[-1][0] == pytest.approx(80.0, abs=0.1)

    def test_ramp_down_ends_at_zero(self):
        ramp = SoftRamp()
        schedule = ramp.generate_ramp_down(from_duty_pct=60.0)
        assert schedule[-1][0] == pytest.approx(0.0, abs=0.1)

    def test_step_count(self):
        cfg = SoftRampConfig(steps=10)
        ramp = SoftRamp(cfg)
        schedule = ramp.generate_ramp_up(50.0)
        assert len(schedule) == cfg.steps + 1

    def test_hold_ms_within_duration(self):
        cfg = SoftRampConfig(ramp_duration_ms=150.0, steps=20)
        ramp = SoftRamp(cfg)
        schedule = ramp.generate_ramp_up(100.0)
        total = sum(h for _, h in schedule)
        # steps+1 entries (both endpoints included), so total = (steps+1) * hold_per_step
        expected = (cfg.steps + 1) * (cfg.ramp_duration_ms / cfg.steps)
        assert abs(total - expected) < 1.0

    def test_monotonic_ramp_up(self):
        ramp = SoftRamp()
        sched = ramp.generate_ramp_up(100.0)
        duties = [d for d, _ in sched]
        assert duties == sorted(duties)


class TestDryFireGuard:
    def test_volume_empty_triggers(self):
        guard = DryFireGuard()
        est = UsageEstimate(total_volume_ul=100.0, remaining_volume_ul=0.0,
                            pulses_delivered=1000, ul_per_pulse=0.1)
        assert guard.check(est, drive_current_ma=100.0) is True

    def test_low_current_triggers(self):
        guard = DryFireGuard()
        assert guard.check(None, drive_current_ma=5.0) is True

    def test_normal_conditions_no_trigger(self):
        guard = DryFireGuard()
        est = UsageEstimate(total_volume_ul=100.0, remaining_volume_ul=50.0,
                            pulses_delivered=10, ul_per_pulse=0.1)
        assert guard.check(est, drive_current_ma=150.0) is False

    def test_reset_clears_flag(self):
        guard = DryFireGuard()
        guard.check(None, drive_current_ma=5.0)
        assert guard.is_triggered
        guard.reset()
        assert not guard.is_triggered
