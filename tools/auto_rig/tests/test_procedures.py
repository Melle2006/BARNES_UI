"""Dry run of the five rig tests on the simulated joint (no hardware).

    python3 tools/auto_rig/tests/test_procedures.py
"""
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_rig.hardware import SimRig  # noqa: E402
from auto_rig.procedures import Runner, RigConfig  # noqa: E402


def runner(rig, **cfg):
    c = RigConfig(slack_us=rig.us0, settle_s=0.0, **cfg)
    out = Path(tempfile.mkdtemp())
    return Runner(rig, rig, c, "SIM-H", out, sleep=rig.sleep, prompt=lambda m: None,
                  say=lambda *a: None, now=lambda: rig.t)


def test_all():
    # H-like joint: lever 2.75 mm, spring 5 N.mm/rad, collars at 74 deg
    rig = SimRig(lever_mm=2.75, k_nmm_per_rad=5.0, theta_max_deg=74, friction_n=0.1)
    r1 = runner(rig).step1().summary
    want30 = 5.0 * math.radians(30) / 2.75
    assert abs(r1["force_to_30deg_n"] - want30) < 0.4, r1
    assert 70 < r1["max_angle_deg"] < 76, r1
    print(f"step1: T to 30 = {r1['force_to_30deg_n']} N (physics {want30:.2f} + friction), "
          f"max angle {r1['max_angle_deg']} deg, stop: {r1['stop_reason']}")

    rig = SimRig(lever_mm=2.75, k_nmm_per_rad=5.0, theta_max_deg=74, friction_n=0.1, W_n=0.981)
    R = runner(rig)
    # the sim's weight is fixed in the model; run one point
    r2 = R.step2(weights_g=(100,)).summary
    p = r2["points"][0]
    want = 0.981 * 44.8 / 2.75
    assert abs(p["T_liftoff_n"] - want) / want < 0.1, p
    print(f"step2 (100 g): lift-off {p['T_liftoff_n']} N (physics {want:.1f}), "
          f"effective lever {p['effective_lever_mm']} mm (design 2.75)")

    rig = SimRig(lever_mm=3.4, k_nmm_per_rad=8.0, theta_max_deg=78, buckle_n=13.0, stop_deg=30, W_n=0.2)
    r3 = runner(rig).step3().summary
    assert "buckle" in r3["mode"] or "twist" in r3["mode"], r3
    assert 11 < r3["peak_force_n"] < 15, r3
    print(f"step3: gave way at {r3['peak_force_n']} N, mode '{r3['mode']}' (sim buckles at 13 N)")

    rig = SimRig(lever_mm=2.75, k_nmm_per_rad=5.0, theta_max_deg=74)
    r4 = runner(rig).step4(record_s=620).summary
    assert r4["held_deg"] and r4["held_deg"] >= 59, r4
    assert r4["angle_10min"] is not None and r4["angle_10min"] < r4["angle_1s"], r4
    print(f"step4: held {r4['held_deg']} deg; after release 1 s {r4['angle_1s']}, 10 s {r4['angle_10s']}, "
          f"60 s {r4['angle_60s']}, 10 min {r4['angle_10min']} deg; within 5 deg: {r4['within_5deg']}")

    rig = SimRig(lever_mm=2.75, k_nmm_per_rad=5.0, theta_max_deg=74)
    r5 = runner(rig).step5(cycles=200, check_every=100).summary
    assert r5["cycles_done"] == 200 and len(r5["checks"]) == 3, r5
    print(f"step5: {r5['cycles_done']} cycles, checks {[(c['cycles'], c['rest_deg'], c['T_30_n']) for c in r5['checks']]}")


if __name__ == "__main__":
    test_all()
    print("procedure dry runs passed")
