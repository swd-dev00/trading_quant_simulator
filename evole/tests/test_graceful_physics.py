"""Unit tests for GracefulPhysics subsystems."""

import pytest
from evole.core.graceful_physics import (
    AntiClogConfig,
    AntiClogManager,
    PrimePurge,
    PrimePurgeConfig,
    ViscosityCompensator,
    ViscosityProfile,
)


class TestPrimePurge:
    def test_schedule_length(self):
        cfg = PrimePurgeConfig(num_bursts=12, purge_cycles=3)
        pp = PrimePurge(cfg)
        sched = pp.generate_schedule()
        assert len(sched) == cfg.num_bursts * cfg.purge_cycles

    def test_last_burst_per_cycle_uses_inter_cycle_pause(self):
        cfg = PrimePurgeConfig(num_bursts=4, purge_cycles=2, inter_cycle_pause_ms=500.0)
        pp = PrimePurge(cfg)
        sched = pp.generate_schedule()
        # Indices of last burst per cycle: 3, 7
        for cycle in range(cfg.purge_cycles):
            last_idx = (cycle + 1) * cfg.num_bursts - 1
            _, off = sched[last_idx]
            assert off == cfg.inter_cycle_pause_ms

    def test_total_duration_positive(self):
        pp = PrimePurge()
        assert pp.total_duration_ms > 0


class TestViscosityCompensator:
    def test_reference_viscosity_no_change(self):
        profile = ViscosityProfile(
            sku="ref",
            dynamic_viscosity_mpa_s=10.0,
            reference_on_time_ms=100.0,
            reference_viscosity_mpa_s=10.0,
        )
        comp = ViscosityCompensator(profile)
        assert abs(comp.adjusted_on_time_ms() - 100.0) < 0.01

    def test_high_viscosity_longer_on_time(self):
        profile = ViscosityProfile(
            sku="oud",
            dynamic_viscosity_mpa_s=40.0,
            reference_on_time_ms=100.0,
            reference_viscosity_mpa_s=10.0,
        )
        comp = ViscosityCompensator(profile)
        assert comp.adjusted_on_time_ms() > 100.0

    def test_low_viscosity_shorter_on_time(self):
        profile = ViscosityProfile(
            sku="citrus",
            dynamic_viscosity_mpa_s=5.0,
            reference_on_time_ms=100.0,
            reference_viscosity_mpa_s=10.0,
        )
        comp = ViscosityCompensator(profile)
        assert comp.adjusted_on_time_ms() < 100.0


class TestAntiClogManager:
    def test_not_due_immediately(self):
        mgr = AntiClogManager()
        assert not mgr.is_maintenance_due()

    def test_stealth_schedule_length(self):
        cfg = AntiClogConfig(stealth_pulse_count=5)
        mgr = AntiClogManager(cfg)
        sched = mgr.generate_stealth_schedule()
        assert len(sched) == 5

    def test_stealth_on_ms_below_perception(self):
        mgr = AntiClogManager()
        for on_ms, _ in mgr.generate_stealth_schedule():
            assert on_ms < 10.0    # below fragrance release threshold
