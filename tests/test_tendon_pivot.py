"""The tendon-anchor optimiser in scripts/tendon_pivot_optimizer.py.

The geometry is checked against quantities computed independently of it -- the
virtual-work identity and closed forms -- rather than against its own earlier output.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tendon_pivot_optimizer.py"
_spec = importlib.util.spec_from_file_location("tendon_pivot_optimizer", _PATH)
tpo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tpo   # dataclasses look their module up here
_spec.loader.exec_module(tpo)

MCP, PIP, DIP = tpo.JOINTS


@pytest.mark.parametrize("offset", [0.0, 0.004])
@pytest.mark.parametrize("spec", tpo.JOINTS, ids=lambda j: j.name)
def test_moment_arm_equals_rate_of_tendon_shortening(spec, offset):
    spec = replace(spec, guide_offset_m=offset, anchor_offset_m=offset)
    for x in (spec.x_min_m, 0.5 * spec.x_max_m, spec.x_max_m):
        assert tpo.check_virtual_work(spec, x) < 1e-9


def test_old_formula_fails_the_virtual_work_check():
    th = np.linspace(0.05, MCP.theta_max_rad, 50)
    x = MCP.x_max_m
    h = 1e-6
    rate = -(tpo.tendon_length(MCP, th + h, x) - tpo.tendon_length(MCP, th - h, x)) / (2 * h)
    old = tpo.old_formula_moment_arm(MCP, th, x)
    assert np.max(np.abs(old - rate)) > 1e-3   # off by over a millimetre


def test_collinear_moment_arm_matches_the_law_of_sines():
    L, x, th = MCP.guide_distance_m, 0.030, 0.8
    expected = L * x * math.sin(th) / math.sqrt(L**2 + x**2 + 2 * L * x * math.cos(th))
    assert tpo.moment_arm(MCP, th, x) == pytest.approx(expected, rel=1e-12)
    assert tpo.moment_arm(MCP, 0.0, x) == pytest.approx(0.0, abs=1e-15)


def test_fingertip_load_on_a_straight_finger_is_force_times_distance():
    f = 2.0
    tau = tpo.fingertip_load_torques(np.zeros(3), fingertip_force_N=f)
    lengths = [j.distal_link_m for j in tpo.JOINTS]
    assert tau == pytest.approx([f * sum(lengths), f * sum(lengths[1:]), f * lengths[2]])


def test_dip_load_does_not_depend_on_the_proximal_angles():
    tau = tpo.fingertip_load_torques(np.array([0.7, 1.1, 0.4]), fingertip_force_N=3.0)
    assert tau[2] == pytest.approx(3.0 * DIP.distal_link_m)


def test_max_margin_design_fits_the_stroke_and_beats_the_upper_bound():
    force, stroke = tpo.actuator(0.010)
    tables = tpo.joint_tables(force)
    picks = tpo.max_margin_design(tables, stroke)
    used = sum(t.excursion[i] for t, i in zip(tables, picks))
    assert used <= stroke
    # The old answer, every anchor at its upper bound, does not fit this stroke.
    assert sum(t.excursion[-1] for t in tables) > stroke
    # And no feasible single-joint change improves the worst margin.
    best = min(t.margin[i] for t, i in zip(tables, picks))
    for j, t in enumerate(tables):
        for k in range(len(t.xs)):
            trial = list(picks)
            trial[j] = k
            if sum(tb.excursion[i] for tb, i in zip(tables, trial)) <= stroke:
                assert min(tb.margin[i] for tb, i in zip(tables, trial)) <= best + 1e-12


def test_min_stroke_design_meets_the_safety_factor_where_it_reports_one():
    joints = tuple(replace(j, guide_offset_m=0.004, anchor_offset_m=0.004)
                   for j in tpo.JOINTS)
    force, _ = tpo.actuator(0.010)
    tables = tpo.joint_tables(force, joints, fingertip_force_N=2.0)
    picks = tpo.min_stroke_design(tables, 1.5)
    assert all(i is not None for i in picks)
    for t, i in zip(tables, picks):
        assert t.margin[i] >= 1.5
        assert t.excursion[i] == t.excursion[t.margin >= 1.5].min()
