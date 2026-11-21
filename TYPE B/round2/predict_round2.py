"""
Predictions for the round-2 PIP rig test, so every measurement has a number
to be checked against.

Rough models, stated so they can be proved wrong:

* Tendon lever about the joint's centre of rotation:
    bending joints (B3, B6, full-length B1 notch, lattice): constant-curvature
        bend, lever from virtual work (scripts/tendon_routing_analysis.py);
    fixed-centre joints (B5, 50 % B1 notch, B9 strut, B8 knuckle): pin at mid
        flex zone, at y = 0 (B8: at the pad, so the lever gains the pad's
        dorsal offset);
    B4 rolling: the contact moves palmar by R sin(theta/2), so the lever is
        d - R sin(theta/2).
* Holding a weight W on the rig's 44.8 mm hook at flexion theta (arm raised
  theta above horizontal): T = (W * 44.8 * cos(theta) + k * theta) / lever.
* Compression capacity, the tension the joint's compression path takes:
    leaves and strips: Euler fixed-fixed buckling (as in docs/11);
    B9 strut: 20 % strain over the neck area;
    B8 knuckle: 20 % strain over the projected bearing area (2 r x lanes);
    B4 rolling: Hertz line contact between two TPU cylinders, peak pressure
        0.2 E (so also ~20 % local strain).
  E = 12 MPa throughout: provisional. Every force here scales with it.
* Collar contact: the 0.8 mm collars meet palmar of a fixed centre at
  2 atan((F/2) / (h_c + y_pivot)). The round-1 FEA put this at about 76 deg
  for the PIP (TYPE B/analysis/relief_rom.py); this simple form gives 67 deg,
  so treat it as conservative.

    python "TYPE B/round2/predict_round2.py"     # writes predictions.csv
"""

import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TYPE_B = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(TYPE_B), "scripts"))
import tendon_routing_analysis as T  # noqa: E402

E = 12.0                  # MPa, provisional
NU = 0.45
HOOK = 44.8               # mm, the rig's fingertip-equivalent hook
FLEX = 7.55               # PIP flex zone
COLLAR_HALF = 5.7         # PIP collar half-height
STRAIN = 0.2
ANGLES = (0, 30, 60)

ROUND1 = {"B1": "B1_hourglass", "B3": "B3_dual_leaf", "B5": "B5_crossed_strip",
          "B6": "B6_multi_leaf", "lattice": "B_lattice"}


def rows(path):
    with open(path) as f:
        return [r for r in csv.DictReader(f) if r["joint"] == "PIP"]


def lever(model, theta, d, extra):
    theta = max(theta, 1e-3)   # the bent-joint derivative is one-sided at exactly 0
    if model == "arc":
        return float(T.arc_moment_arm(theta, FLEX, d))
    if model == "rolling":
        return d - extra * math.sin(theta / 2)
    return float(T.pin_moment_arm(theta, FLEX / 2, FLEX / 2, d + extra))


def record(name, family, model, d, extra, k, p_cap, cap_basis, pivot_y=0.0):
    out = dict(variant=name, family=family, kinematic_model=model,
               tendon_offset_mm=round(d, 2), k_Nmm_per_rad=round(k, 2) if k == k else "",
               compression_capacity_N=round(p_cap, 1) if p_cap == p_cap else "",
               capacity_basis=cap_basis)
    for a in ANGLES:
        th = math.radians(a)
        r = lever(model, th, d, extra)
        out[f"lever_{a}deg_mm"] = round(r, 2)
        kk = 0.0 if k != k else k
        t_per_N = (HOOK * math.cos(th)) / r if r > 0 else float("inf")
        out[f"tension_per_N_hook_{a}deg"] = round(t_per_N, 1)
        out[f"tension_unloaded_{a}deg_N"] = round(kk * th / r, 2) if r > 0 else "lever <= 0"
    worst = max(out[f"tension_per_N_hook_{a}deg"] for a in ANGLES)
    out["hook_N_at_capacity"] = round(p_cap / worst, 2) if p_cap == p_cap else ""
    out["collar_contact_deg"] = round(math.degrees(2 * math.atan(FLEX / 2 / (COLLAR_HALF + pivot_y))), 0)
    return out


def main():
    out = []
    caps = {r["variant"]: r for r in T.type_b_variants() if r["joint"] == "PIP"}
    deep = rows(os.path.join(HERE, "deep_offset", "variants_summary.csv"))
    new = rows(os.path.join(HERE, "variants_summary.csv"))
    for r in new + deep:
        name, fam = r["variant"], r["family"]
        d = float(r["tendon_moment_arm_mm"])
        src = r.get("source") or name
        if fam in ("B4", "B8", "B9"):
            k = float(r["k_over_E_mm3"]) * E
            w_tot = float(r["bearing_w_total"])
            if fam == "B4":
                R = float(r["roll_r_mm"])
                e_star = E / (2 * (1 - NU ** 2))
                p0 = STRAIN * E
                cap = math.pi * w_tot * (R / 2) * p0 ** 2 / e_star
                out.append(record(name, fam, "rolling", d, R, k, cap, "Hertz, p0 = 0.2E"))
            elif fam == "B8":
                rk, yp = float(r["knuckle_r_mm"]), float(r["pivot_y_mm"])
                cap = STRAIN * E * 2 * rk * w_tot
                out.append(record(name, fam, "pivot", d, yp, k, cap, "20 % strain, knuckle", yp))
            else:
                cap = STRAIN * E * float(r["neck_area_mm2"])
                out.append(record(name, fam, "pivot", d, 0.0, k, cap, "20 % strain, neck"))
        else:
            c = caps[src]
            model = "arc" if c["model"] == "arc" else "pivot"
            k = c["k"]
            out.append(record(name, fam, model, d, 0.0, k, c["p_cr"], "Euler buckling"))
    # round-1 originals of the shortlisted variants, for side-by-side
    for fam, names in (("B1", ("B1_t100_notch100", "B1_t200_notch050")), ("B3", ("B3_t100_w20", "B3_t200_w30")),
                       ("B5", ("B5_t100_a75", "B5_t200_a45")), ("B6", ("B6_n6_t100", "B6_n4_t200")),
                       ("lattice", ("B_T090_X3", "B_T120_X3"))):
        for n in names:
            c = caps[n]
            out.append(record(n, fam, "arc" if c["model"] == "arc" else "pivot", c["d"], 0.0,
                              c["k"], c["p_cr"], "Euler buckling"))
    fields = list(out[0])
    with open(os.path.join(HERE, "predictions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(f"{r['variant']:24} lever0 {r['lever_0deg_mm']:5} lever60 {r['lever_60deg_mm']:5} "
              f"k {r['k_Nmm_per_rad']!s:6} T/N@0 {r['tension_per_N_hook_0deg']:5} "
              f"cap {r['compression_capacity_N']!s:7} hook@cap {r['hook_N_at_capacity']!s:6} "
              f"collar {r['collar_contact_deg']}")


if __name__ == "__main__":
    main()
