"""Put every design's headline numbers on one material basis: SUNLU TPU 90A.

Why this is a rescale and not a re-run
--------------------------------------
Every FEA and reduced-order result in this repository uses a Neo-Hookean (or linear)
TPU and is either displacement-driven (a joint bent to an angle) or, for the round-2
tendon runs, force-driven with a contact penalty proportional to E. In both cases
strains, angles, ranges and rankings do not depend on E, and every moment, force,
stress, capacity and stiffness is exactly proportional to it. So changing the modulus
is a multiplication, and running the solver again would give the same numbers.

The studies were not on the same basis: Type B and A3 at 12 MPa, A6 at 13 MPa, A8 at
19.3 MPa (Jabil TPU 90A datasheet). This script brings them together.

What SUNLU publishes, and what it does not
------------------------------------------
The filament in use is SUNLU TPU 90A, 1.75 mm. Its product page gives density
1.23 g/cm^3 and tensile strength 40 +/- 6 MPa, and *no* modulus; see
docs/06-required-inputs.md item 7. So:

* density is SUNLU's: 1.23 g/cm^3;
* the modulus is not available from SUNLU. Results are quoted at a working 12 MPa
  (the value most of the project already uses) and across a bracket of 5.3 MPa (a
  printed TPU 90A, Bambu Lab's datasheet, XY direction) to 19.3 MPa (bulk TPU 90A,
  Jabil's datasheet). Where a pass/fail gate depends on E (the return gate, whether
  the tendon can bend a joint without buckling it) it is evaluated at both ends.

Replace ``E_SUNLU_MPA`` with a tensile-test value and re-run; nothing else changes.

    python scripts/sunlu_rescale.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results" / "sunlu_rescale"

DENSITY_G_CM3 = 1.23          # SUNLU TPU 90A product page
E_SUNLU_MPA = None            # not published by SUNLU; set from a tensile test
E_WORK_MPA = 12.0             # working value until then
E_LOW_MPA, E_HIGH_MPA = 5.3, 19.3

#: modulus each study was run at
E_RUN = {"A3": 12.0, "A6": 13.0, "A8": 19.3, "TypeB_r1": 12.0, "TypeB_r2": 12.0}

#: servo tension available (docs/11: MG995 at half stall on a 10 mm horn)
SERVO_TENSION_N = 47.0
#: PIP lever to the fingertip hook, and the tendon offsets (TEST_PLAN.md)
HOOK_MM = 44.8
TENDON_D = {"as-built": 1.93, "deep": 3.40}


def scale(value, study, e):
    return None if value is None else value * e / E_RUN[study]


def rows():
    out = []

    def add(design, quantity, unit, value, study, note=""):
        e_work = E_SUNLU_MPA or E_WORK_MPA
        out.append(dict(design=design, quantity=quantity, unit=unit, study_E_mpa=E_RUN[study],
                        value_as_run=value, at_low=scale(value, study, E_LOW_MPA),
                        at_work=scale(value, study, e_work), at_high=scale(value, study, E_HIGH_MPA),
                        note=note))

    a3 = json.loads((REPO / "results/a3_mesh_study/study.json").read_text())
    add("A3 twin strap 1.0 mm", "rotational stiffness at neutral (FEA)", "N.mm/rad",
        a3["points"][-1]["stiffness_n_mm_per_rad"], "A3", "pin-hinged, mesh-converged 0.94 %")
    add("A6 R32 / 1.8 / 6", "worst-case torque at 105 deg", "N.mm", 2.28, "A6", "results/a6/README.md")
    add("A6 R28 / 1.4 / 6", "worst-case torque at 105 deg", "N.mm", 0.71, "A6", "results/a6/README.md")
    a8 = json.loads((REPO / "results/a8_index_pip_printable/cases/print_2T_w1.2_h2.4_s2.75.json").read_text())
    for ang in ("30", "60", "90"):
        add("A8 2-turn printable s2.75", f"restoring torque at {ang} deg", "N.mm",
            a8["torque_n_mm"][ang], "A8")
    add("A8 2-turn printable s2.75", "initial stiffness", "N.mm/rad", a8["k0_n_mm_per_rad"], "A8")
    s3 = REPO / "results/a8_index_pip_printable/cases/print_2T_w1.2_h2.4_s3.00.json"
    if s3.exists():
        a = json.loads(s3.read_text())
        add("A8 2-turn printable s3.00", "restoring torque at 90 deg", "N.mm", a["torque_n_mm"]["90"], "A8")

    for p in sorted((REPO / "results/a8_collared/cases").glob("collared_*.json")):
        r = json.loads(p.read_text())
        if "failure" in r or not r.get("torque_n_mm"):
            continue
        for ang in ("30", "60", "90"):
            add(f"A8 2-turn with collars s{r['sagitta']:.2f}", f"restoring torque at {ang} deg", "N.mm",
                r["torque_n_mm"][ang], "A8", "A3 fit-check collars as TPU")

    summ = list(csv.DictReader(open(REPO / "TYPE B/analysis/results/summary_PIP.csv")))
    for r in summ:
        if r["eligible"] != "True" and float(r["return_margin"] or 0) < 0.5:
            continue
        add(r["variant"], "return margin (moment at 20 deg / finger weight moment)", "x",
            float(r["return_margin"]), "TypeB_r1", "passes when >= 1")
        add(r["variant"], "tendon force at end of range", "N", float(r["tendon_force_N"]), "TypeB_r1")

    for p in sorted((REPO / "TYPE B/round2/fea/results").glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("capacity_T") is None:
            continue
        name = r["variant"] + ("_deep" if r["offset"] == "deep" else "")
        add(name, f"tendon capacity at {r['angle']:g} deg", "N", r["capacity_T"], "TypeB_r2",
            r.get("limited_by", ""))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rs = rows()
    with open(OUT / "headline_values.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0]))
        w.writeheader()
        for r in rs:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    meta = dict(density_g_cm3=DENSITY_G_CM3, E_sunlu_mpa=E_SUNLU_MPA, E_work_mpa=E_WORK_MPA,
                E_bracket_mpa=[E_LOW_MPA, E_HIGH_MPA], E_as_run=E_RUN,
                servo_tension_N=SERVO_TENSION_N,
                sources={"density": "SUNLU TPU 90A product page (docs/06-required-inputs.md item 7)",
                         "E_low": "Bambu Lab TPU 90A technical data sheet, printed XY, 5.3 +/- 0.7 MPa",
                         "E_high": "Jabil TPU 90A datasheet, 19.3 MPa (used by the A8 study)"})
    (OUT / "basis.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(rs)} rows -> {OUT / 'headline_values.csv'}")


if __name__ == "__main__":
    main()
