"""Unit tests for PulseEngine and rate limiter."""

import time
import pytest
from evole.core.pulse_engine import (
    BurstRateLimiter,
    PulseEngine,
    _max_on_ms_for_temp,
)


class TestMaxOnMsForTemp:
    def test_reference_temp(self):
        cap = _max_on_ms_for_temp(20.0)
        assert abs(cap - 400.0) < 1.0

    def test_hot_ambient_caps_lower(self):
        hot = _max_on_ms_for_temp(40.0)
        ref = _max_on_ms_for_temp(20.0)
        assert hot < ref

    def test_cold_ambient_allows_longer(self):
        cold = _max_on_ms_for_temp(10.0)
        ref = _max_on_ms_for_temp(20.0)
        assert cold > ref

    def test_never_below_50ms(self):
        assert _max_on_ms_for_temp(80.0) >= 50.0

    def test_never_above_600ms(self):
        assert _max_on_ms_for_temp(-10.0) <= 600.0


class TestBurstRateLimiter:
    def test_low_intensity_always_allowed(self):
        lim = BurstRateLimiter(max_high_bursts=1, high_threshold=7)
        for _ in range(10):
            assert lim.is_allowed(5) is True

    def test_high_intensity_rate_limited(self):
        lim = BurstRateLimiter(max_high_bursts=3, window_s=60.0, high_threshold=7)
        for _ in range(3):
            assert lim.is_allowed(8)
            lim.record_event(8)
        # 4th event should be denied
        assert lim.is_allowed(8) is False


class TestPulseEngine:
    def test_returns_empty_on_rate_limit(self):
        engine = PulseEngine(BurstRateLimiter(max_high_bursts=0, high_threshold=1))
        sched = engine.build_schedule(10, 100, 0)
        assert len(sched.pulses) == 0

    def test_full_a_no_b_pulses(self):
        engine = PulseEngine()
        sched = engine.build_schedule(5, 100.0, 0.0)
        b_pulses = [p for p in sched.pulses if p.channel == 1]
        assert len(b_pulses) == 0

    def test_full_b_no_a_pulses(self):
        engine = PulseEngine()
        sched = engine.build_schedule(5, 0.0, 100.0)
        a_pulses = [p for p in sched.pulses if p.channel == 0]
        assert len(a_pulses) == 0

    def test_hot_temp_caps_on_time(self):
        engine = PulseEngine()
        sched_hot = engine.build_schedule(10, 100.0, 0.0, temp_celsius=40.0)
        sched_ref = engine.build_schedule(10, 100.0, 0.0, temp_celsius=20.0)
        max_hot = max(p.on_ms for p in sched_hot.pulses) if sched_hot.pulses else 0
        max_ref = max(p.on_ms for p in sched_ref.pulses) if sched_ref.pulses else 0
        assert max_hot <= max_ref + 1.0   # hot should not exceed reference

    def test_higher_intensity_more_pulses(self):
        engine = PulseEngine()
        low = engine.build_schedule(2, 50.0, 50.0)
        high = engine.build_schedule(9, 50.0, 50.0)
        assert len(high.pulses) >= len(low.pulses)

    def test_micro_burst_sequence(self):
        engine = PulseEngine()
        sched = engine.micro_burst_sequence(count=3, channel=0)
        assert len(sched.pulses) == 3
        for p in sched.pulses:
            assert p.on_ms == 50.0
            assert p.channel == 0
