"""The Type A / Type B tendon-routing analysis in scripts/tendon_routing_analysis.py.

Each geometric function is checked against something computed another way: the
pinned-joint lever against the earlier, separately tested module; the bent-joint
lever against the virtual-work identity and its small-angle limit; the centre of
rotation of a constant-curvature joint against its known start at mid-span.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tra = _load("tendon_routing_analysis")
tpo = _load("tendon_pivot_optimizer")


@pytest.mark.parametrize("a,x,h", [(20.0, 15.0, 0.0), (8.0, 9.0, 4.0), (40.0, 6.0, 6.5)])
def test_pinned_lever_matches_the_tested_module(a, x, h):
    spec = replace(tpo.JOINTS[0], guide_distance_m=a, guide_offset_m=h, anchor_offset_m=h)
    th = np.linspace(0.0, 1.8, 30)
    assert tra.pin_moment_arm(th, a, x, h) == pytest.approx(
        tpo.moment_arm(spec, th, x), rel=1e-12, abs=1e-12)
    assert tra.pin_tendon_length(th, a, x, h) == pytest.approx(
        tpo.tendon_length(spec, th, x), rel=1e-12)


def test_pinned_lever_is_the_offset_when_straight():
    assert tra.pin_moment_arm(0.0, 12.0, 9.0, 4.5) == pytest.approx(4.5)


@pytest.mark.parametrize("L,d", [(7.55, 1.93), (10.25, 3.06), (7.3, 0.0)])
def test_bent_joint_lever_satisfies_virtual_work(L, d):
    th = np.linspace(0.05, 1.8, 40)
    step = 1e-6
    rate = -(tra.arc_tendon_length(th + step, L, d)
             - tra.arc_tendon_length(th - step, L, d)) / (2 * step)
    assert tra.arc_moment_arm(th, L, d) == pytest.approx(rate, rel=1e-5, abs=1e-8)


def test_bent_joint_closed_form():
    # l = 2 (L/theta - d) sin(theta/2); at theta = pi/2, L = 8, d = 2:
    L, d, th = 8.0, 2.0, math.pi / 2
    assert tra.arc_tendon_length(th, L, d) == pytest.approx(
        2 * (L / th - d) * math.sin(th / 2))
    # Straight, the tendon spans the flex zone and the lever is exactly d.
    assert tra.arc_tendon_length(1e-9, L, d) == pytest.approx(L)
    assert tra.arc_moment_arm(1e-4, L, d) == pytest.approx(d, abs=1e-3)


def test_bending_centre_starts_at_mid_span_and_moves():
    L = 7.55
    along, palmar = tra.arc_centre_of_rotation(np.array([1e-4, 1.5]), L)
    assert along[0] == pytest.approx(L / 2, abs=1e-3)
    assert palmar[0] == pytest.approx(0.0, abs=1e-3)
    assert abs(along[1] - L / 2) > 0.1 or abs(palmar[1]) > 0.1


def test_fingertip_statics_straight_finger():
    tau = tra.fingertip_load_torques(np.zeros(3), [40.0, 25.0, 20.0], 2.0)
    assert tau == pytest.approx([170.0, 90.0, 40.0])


def test_pareto_front_is_non_dominated():
    rng = np.random.default_rng(1)
    m, e = rng.random(300), rng.random(300)
    front = tra.pareto(m, e)
    for i in front:
        assert not np.any((m > m[i]) & (e < e[i]))


def test_coupled_choice_fits_the_stroke():
    rng = np.random.default_rng(2)
    fronts = [(np.sort(rng.random(20)), np.sort(rng.random(20)) * 20) for _ in range(3)]
    pick = tra.couple(fronts, 25.0)
    assert sum(f[1][i] for f, i in zip(fronts, pick)) <= 25.0
    assert tra.couple(fronts, -1.0) is None


def test_type_b_buckling_load_is_euler_fixed_fixed():
    rec = next(r for r in tra.type_b_variants()
               if r["variant"] == "B3_t100_w30" and r["joint"] == "PIP")
    E, w, t, L = tra.MODULUS_MPA, 3.0, 1.0, 7.55
    assert rec["p_cr"] == pytest.approx(2 * 4 * math.pi**2 * E * w * t**3 / 12 / L**2)


def test_grasp_angles_shape_follows_input():
    assert tra.grasp_angles(1.2).shape == (tra.N_POSE,)
    assert tra.grasp_angles(np.array([1.0, 1.5, 1.2])).shape == (tra.N_POSE, 3)
