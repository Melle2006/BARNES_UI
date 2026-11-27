"""Printed parts for the automated rig, with the flag checked against the rig through 0-115 deg.

    python3 tools/auto_rig/cad/build_auto_rig_parts.py        # needs CadQuery

* FLG marker flag: a 1.2 mm plate on the camera side of the load adapter's arm, held by two pegs
  pushed into the 30 and 37.5 mm hook holes (the 44.8 mm hole stays free for the fingertip
  hanger). The moving ArUco marker (14 mm) is glued on it. About 0.5 g, 33.75 mm from the pivot:
  0.15 N.mm, under 3 % of the lightest spring moment, and the zero is taken with it fitted.
* SPL winch spool: 20 mm core (0.0244 mm of line per microsecond of a 280-deg servo), flanges,
  a radial hole and knot pocket for the line, and screw holes to bolt it to the servo's round horn.
* BRK servo bracket for a standard-size servo (40.5 x 20.2 mm body, ears 49.5 x 10 mm hole
  pattern: check yours and change SERVO_* below), with a base flange to screw or clamp down.
Writes print_ready/auto_rig/*.stl and .step and checks.csv.
"""
from __future__ import annotations
import csv, math, sys
from pathlib import Path
import cadquery as cq

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "print_ready" / "auto_rig"
sys.path.insert(0, str(REPO / "TYPE B" / "round2" / "test_rig"))
sys.path.insert(0, str(REPO / "TYPE B"))
import build_test_rig as T  # noqa: E402

SERVO_BODY = (40.5, 20.2)       # mm
SERVO_HOLES = (49.5, 10.0)      # ear hole pattern, mm
SERVO_SCREW_D = 3.0


def flag(pz):
    z0, z1 = pz + 26.0, pz + 41.0
    plate = cq.Workplane("YZ").workplane(offset=3.05).center(0, (z0 + z1) / 2).rect(20.0, z1 - z0).extrude(1.2)
    plate = plate.edges("|X").fillet(1.0)
    for r in (30.0, 37.5):
        peg = cq.Workplane("YZ").workplane(offset=-2.6).center(0, pz + r).circle(1.15).extrude(5.65)
        plate = plate.union(peg)
    return plate.val()


def spool():
    core = cq.Workplane("XY").circle(10.0).extrude(6.0)
    fl1 = cq.Workplane("XY").workplane(offset=-1.5).circle(17.0).extrude(1.5)
    fl2 = cq.Workplane("XY").workplane(offset=6.0).circle(17.0).extrude(1.5)
    s = core.union(fl1).union(fl2)
    s = s.cut(cq.Workplane("XY").workplane(offset=-2).circle(1.6).extrude(12))           # horn screw
    for r, n in ((7.0, 4), (9.5, 4)):
        for k in range(n):
            a = 2 * math.pi * k / n + (math.pi / 4 if r > 8 else 0)
            s = s.cut(cq.Workplane("XY").workplane(offset=-2).center(r * math.cos(a), r * math.sin(a))
                      .circle(0.9).extrude(12))
    s = s.cut(cq.Workplane("YZ").workplane(offset=-12).center(0, 3.0).circle(0.6).extrude(24))   # line hole
    s = s.cut(cq.Workplane("XY").workplane(offset=1.5).center(0, -6.0).rect(3.0, 3.0).extrude(3.0))  # knot pocket
    return s.val()


def bracket():
    bw, bh, t = 62.0, 34.0, 4.0
    plate = cq.Workplane("XZ").rect(bw, bh).extrude(t)
    plate = plate.cut(cq.Workplane("XZ").rect(SERVO_BODY[0] + 0.6, SERVO_BODY[1] + 0.6).extrude(t + 1))
    for sx in (-1, 1):
        for sz in (-1, 1):
            plate = plate.cut(cq.Workplane("XZ").center(sx * SERVO_HOLES[0] / 2, sz * SERVO_HOLES[1] / 2)
                              .circle(SERVO_SCREW_D / 2 - 0.3).extrude(t + 1))
    base = cq.Workplane("XY").workplane(offset=-bh / 2).center(0, -20).rect(bw, 40.0).extrude(t)
    for sx in (-1, 1):
        base = base.cut(cq.Workplane("XY").workplane(offset=-bh / 2 - 1).center(sx * 22, -26).slot2D(12, 5, 90).extrude(t + 2))
    g = []
    for sx in (-1, 1):
        g.append(cq.Workplane("YZ").workplane(offset=sx * (bw / 2 - 3) - 1.5)
                 .polyline([(0, -bh / 2 + t), (-25, -bh / 2 + t), (0, bh / 2 - 4)]).close().extrude(3.0))
    b = plate.union(base)
    for x in g:
        b = b.union(x)
    return b.val()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    g = T.geometry()
    pz = g["pivot_z"]
    base, _ = T.rig_base(g)
    adapter = T.load_adapter(g, T.anchor_for(g, "deep"))
    f = flag(pz)
    rows = []
    v = f.intersect(adapter).Volume()
    # pegs are meant to sit in the hook holes: only the plate must not overlap the adapter
    plate_only = f.cut(cq.Workplane("YZ").workplane(offset=-3).rect(100, 200).extrude(6.0).val())
    rows.append(dict(check="flag plate clear of the load adapter", value=round(plate_only.intersect(adapter).Volume(), 4)))
    rows.append(dict(check="flag pegs inside the hook holes (overlap with adapter)", value=round(v, 4)))
    worst = 0.0
    ph2 = T.ph2_at(g)
    for deg in range(0, 116, 5):
        mv = T.rotate_about_pivot(f, deg, pz)
        worst = max(worst, mv.intersect(base).Volume())
    rows.append(dict(check="flag clear of the rig base, 0-115 deg", value=round(worst, 4)))
    rows.append(dict(check="flag clear of Phalanx 2", value=round(f.intersect(ph2).Volume(), 4)))
    mass_g = plate_only.Volume() * 1.24e-3 + (f.Volume() - plate_only.Volume()) * 1.24e-3
    rows.append(dict(check="flag mass (g, PLA)", value=round(mass_g, 3)))
    for name, shp in (("FLG_marker_flag", f), ("SPL_winch_spool", spool()), ("BRK_servo_bracket", bracket())):
        wp = cq.Workplane("XY").newObject([shp])
        cq.exporters.export(wp, str(OUT / f"{name}.step"))
        cq.exporters.export(wp, str(OUT / f"{name}.stl"), tolerance=0.02, angularTolerance=0.2)
    with open(OUT / "checks.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["check", "value"]); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"  {r['check']}: {r['value']}")


if __name__ == "__main__":
    main()
