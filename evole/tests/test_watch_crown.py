"""Unit tests for WatchCrownController."""

import pytest
from evole.core.watch_crown import (
    CrownPosition,
    DialLabel,
    ScentMemory,
    WatchCrownController,
    _adc_to_label,
    _adc_to_setup_grade,
)


class TestAdcToLabel:
    def test_left_sector(self):
        assert _adc_to_label(0) == DialLabel.MORN
        assert _adc_to_label(200) == DialLabel.MORN

    def test_middle_sector(self):
        assert _adc_to_label(512) == DialLabel.WORK

    def test_right_sector(self):
        assert _adc_to_label(900) == DialLabel.NIGHT
        assert _adc_to_label(1023) == DialLabel.NIGHT


class TestAdcToSetupGrade:
    def test_min_grade(self):
        assert _adc_to_setup_grade(0) == 1

    def test_max_grade(self):
        assert _adc_to_setup_grade(1023) == 10

    def test_midpoint(self):
        grade = _adc_to_setup_grade(512)
        assert 4 <= grade <= 6


class TestScentMemory:
    def test_save_and_load(self):
        mem = ScentMemory()
        mem.save("citrus-01", DialLabel.MORN, 3)
        assert mem.load("citrus-01", DialLabel.MORN) == 3

    def test_unknown_sku_returns_default(self):
        mem = ScentMemory()
        grade = mem.load("unknown-sku", DialLabel.NIGHT)
        assert grade == 6   # default for NIGHT

    def test_has_memory(self):
        mem = ScentMemory()
        assert not mem.has_memory("x")
        mem.save("x", DialLabel.WORK, 5)
        assert mem.has_memory("x")


class TestWatchCrownController:
    def test_initial_state_active_mode(self):
        ctrl = WatchCrownController()
        assert ctrl.state.position == CrownPosition.PUSHED_IN
        assert ctrl.pumps_enabled

    def test_pull_out_gates_pumps(self):
        ctrl = WatchCrownController()
        ctrl.on_crown_toggle(is_pulled_out=True)
        assert ctrl.state.position == CrownPosition.PULLED_OUT
        assert not ctrl.pumps_enabled
        assert ctrl.state.is_pump_gated

    def test_push_back_in_enables_pumps(self):
        ctrl = WatchCrownController()
        ctrl.on_crown_toggle(is_pulled_out=True)
        ctrl.on_crown_toggle(is_pulled_out=False)
        assert ctrl.pumps_enabled
        assert ctrl.state.position == CrownPosition.PUSHED_IN

    def test_push_back_in_haptic_confirmation(self):
        ctrl = WatchCrownController()
        ctrl.on_crown_toggle(is_pulled_out=True)
        ctrl.on_crown_toggle(is_pulled_out=False)
        assert ctrl.consume_haptic() >= 1

    def test_setup_mode_blocks_spray(self):
        ctrl = WatchCrownController()
        ctrl.on_crown_toggle(is_pulled_out=True)
        state = ctrl.tick(adc=1023, dt=2.0, ampoule_present=True)
        assert state.is_pump_gated

    def test_dwell_fires_callback(self):
        fired = []
        ctrl = WatchCrownController(on_fire=lambda lbl, grade: fired.append((lbl, grade)))
        # Stay at MORN label for > 0.8 s
        ctrl.tick(adc=100, dt=0.9, ampoule_present=True)
        assert len(fired) == 1
        assert fired[0][0] == DialLabel.MORN

    def test_no_fire_without_ampoule(self):
        fired = []
        ctrl = WatchCrownController(on_fire=lambda lbl, grade: fired.append((lbl, grade)))
        ctrl.tick(adc=100, dt=1.0, ampoule_present=False)
        assert len(fired) == 0

    def test_scent_memory_saved_on_push_in(self):
        mem = ScentMemory()
        ctrl = WatchCrownController(memory=mem)
        ctrl.on_ampoule_change("oud-99")
        ctrl.on_crown_toggle(is_pulled_out=True)
        # In setup mode, rotate to grade 8
        ctrl.tick(adc=880, dt=0.1, ampoule_present=True)
        ctrl.on_crown_toggle(is_pulled_out=False)
        saved = mem.load("oud-99", ctrl.state.label)
        assert saved == ctrl.state.intensity_grade

    def test_over_rotate_sets_turbo(self):
        ctrl = WatchCrownController()
        # Simulate holding at hard stop (adc=970) for 2+ seconds
        ctrl.tick(adc=970, dt=2.1, ampoule_present=True)
        assert ctrl.state.turbo_active
