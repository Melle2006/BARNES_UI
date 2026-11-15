"""B5 with a hinge pin: the tendon's compression goes through a pin, the B5 only springs.

    python "TYPE B/round2/b5_pinned.py" [module_folder]     # needs CadQuery

Round 2's FEA showed the Type B joints fail by the tendon's squeeze long before the
servo's limit (plain leaves buckle near 10 N; the best, B5 t2.0 with the deep tendon,
carries about 30 N). This hybrid takes the squeeze out of the TPU entirely: PLA hinge
plates on the two phalanges, outside the joint module, overlap across the flex zone and
are pinned together on the B5's own pivot (mid flex zone, on the neutral axis), so

    tendon squeeze: phalanx -> plate -> pin -> plate -> phalanx   (PLA and steel)
    return spring:  the unchanged B5 module between the phalanges   (TPU)

A pin only suits a flexure that already turns about a fixed point; the B5's crossed strips
do (its centre drifts 0.7-0.9 mm over the range in the round-1 FEA). The module itself is
not changed, so it still plugs into the phalanges as before.

Geometry, in each phalanx's own frame (the builder's: +Z along the finger):
* the pin is 4.575 mm beyond each phalanx's joint face (the 0.8 mm collar plus half the
  7.55 mm PIP flex zone), at x = y = 0 laterally... i.e. on the joint's neutral axis;
* proximal phalanx plates: 1.2 mm thick, from just outside the module's collar (0.3 mm
  clear) outward, fused to the phalanx's sides over 8 mm;
* middle phalanx plates: 1.2 mm, outboard of those (0.2 mm between plates), on a bridge
  fused to the middle phalanx's sides;
* every plate ends in a disc of radius PLATE_R round the pin, smaller than the 4.575 mm
  to the other phalanx's face, so no plate can reach the other phalanx at any angle;
* a Ø2 mm pin (steel dowel, or 1.75 mm filament in a 1.8 mm hole) through each pair.

Writes TYPE B/round2/pinned_b5/: the two PLA phalanges with plates (STEP, STL), an
assembly with the module, and checks.json (plates clear of the module, rigid flexion
clearance, pin and plate strength by hand).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
OUT = HERE / "pinned_b5"
PHAL = HERE / "deep_offset" / "deep_phalanges"

PIN_FROM_FACE = 0.8 + 7.55 / 2       # collar + half the PIP flex zone
COLLAR_HALF = 6.7                    # PIP collar half-width (13.4 mm)
PLATE_T = 1.2
PLATE_GAP = 0.2                      # between the two plates of a side
MODULE_CLEAR = 0.3                   # plate to collar
PLATE_H = 8.0                        # plate height (y), centred on the neutral axis
PLATE_R = 4.0                        # disc round the pin; must stay under PIN_FROM_FACE
ATTACH = 8.0                         # length fused to the phalanx's side
PIN_D = 2.0
#: Pin offset across the finger, mm (+Y is dorsal): the free B5's rotation pole drifts
#: palmar as it bends (round-1 FEA, about 1.1 mm by 90 deg); a pin 0.5 mm palmar of the
#: strip crossing follows it best (pinned FEA, TYPE B/analysis/results/PIP_pinned/).
PIN_DY = -0.5
PIN_HOLE = 2.05

# hand calculation inputs
SERVO_T = 47.0                       # N, the servo's usable tendon tension
PLA_BEARING = 30.0                   # MPa, conservative for printed PLA
STEEL_SHEAR = 300.0                  # MPa, plain steel dowel
FRICTION = 0.3                       # PLA on steel, dry


def plate(x0, x1, z_end_body, z_pin, body_side, dy=0.0):
    """A plate from x0 to x1 (both > 0, mirrored later), running from the phalanx body
    (ATTACH mm onto it) to a disc round the pin."""
    zb = z_end_body - ATTACH if body_side == "proximal" else z_end_body + ATTACH
    z_lo, z_hi = sorted((zb, z_pin))
    bar = cq.Workplane("XY").box(x1 - x0, PLATE_H, z_hi - z_lo, centered=(False, True, False)).translate((x0, 0, z_lo))
    disc = (cq.Workplane("YZ").workplane(offset=x0).center(dy, z_pin).circle(PLATE_R).extrude(x1 - x0))
    return bar.union(disc)


def side_extent(solid, z):
    """Half-width of the phalanx at height z (largest |x| of its section there)."""
    sec = solid.intersect(cq.Workplane("XY").box(60, 60, 0.4).translate((0, 0, z)).val())
    bb = sec.BoundingBox()
    return max(abs(bb.xmin), abs(bb.xmax))


def build(module_folder: Path, dy: float = PIN_DY):
    p1 = cq.importers.importStep(str(PHAL / "02_Phalanx1.step")).val()
    p2 = cq.importers.importStep(str(PHAL / "04_Phalanx2.step")).val()
    mod = cq.importers.importStep(str(module_folder / "03_PIP_module.step")).val()
    z1 = p1.BoundingBox().zmax                     # P1's joint face (distal end)
    z2 = p2.BoundingBox().zmin                     # P2's joint face (proximal end)
    pin1, pin2 = z1 + PIN_FROM_FACE, z2 - PIN_FROM_FACE
    w1, w2 = side_extent(p1, z1 - 2.0), side_extent(p2, z2 + 2.0)
    a0 = COLLAR_HALF + MODULE_CLEAR                # inner plate's inner face
    a1 = a0 + PLATE_T
    b0 = a1 + PLATE_GAP
    b1 = b0 + PLATE_T
    parts1, parts2 = [], []
    for sx in (1, -1):
        m = (lambda w: w.mirror("YZ")) if sx < 0 else (lambda w: w)
        # P1: plate, plus a bridge from its side out to the plate over the attach length
        pl1 = plate(a0, a1, z1, pin1, "proximal", dy)
        br1 = cq.Workplane("XY").box(a1 - (w1 - 0.6), PLATE_H, ATTACH, centered=(False, True, False)).translate(
            (w1 - 0.6, 0, z1 - ATTACH))
        parts1.append(m(pl1.union(br1)))
        pl2 = plate(b0, b1, z2, pin2, "distal", dy)
        br2 = cq.Workplane("XY").box(b1 - (w2 - 0.6), PLATE_H, ATTACH - 0.3, centered=(False, True, False)).translate(
            (w2 - 0.6, 0, z2 + 0.3))
        parts2.append(m(pl2.union(br2)))
    hole1 = cq.Workplane("YZ").workplane(offset=-20).center(dy, pin1).circle(PIN_HOLE / 2).extrude(40)
    hole2 = cq.Workplane("YZ").workplane(offset=-20).center(dy, pin2).circle(PIN_HOLE / 2).extrude(40)
    # the holes must not cut the module region: only through the plates (|x| > a0)
    keep_out = cq.Workplane("XY").box(2 * a0, 40, 40)
    hole1, hole2 = hole1.cut(keep_out), hole2.cut(keep_out)
    P1 = cq.Workplane().add(p1)
    for q in parts1:
        P1 = P1.union(q)
    P1 = P1.cut(hole1)
    P2 = cq.Workplane().add(p2)
    for q in parts2:
        P2 = P2.union(q)
    P2 = P2.cut(hole2)
    return dict(P1=P1.val(), P2=P2.val(), module=mod, dy=dy, z1=z1, z2=z2, pin1=pin1, pin2=pin2,
                plates=dict(p1=(a0, a1), p2=(b0, b1)), widths=(w1, w2))


def place(geo):
    """Module and P2 in P1's frame: the module's proximal collar face on P1's joint face."""
    mod = geo["module"]
    mb = mod.BoundingBox()
    tab = 4.0                                     # PIP tab length
    dz_mod = geo["z1"] - (mb.zmin + tab)
    module_in_p1 = mod.moved(cq.Location(cq.Vector(0, 0, dz_mod)))
    dz_p2 = geo["pin1"] - geo["pin2"]
    return module_in_p1, dz_p2


def checks(geo):
    module, dz_p2 = place(geo)
    P1, P2 = geo["P1"], geo["P2"]
    vol = lambda s: s.Volume()  # noqa: E731

    def overlap(a, b):
        try:
            return round(vol(a.intersect(b)), 3)
        except Exception:
            return None
    p2_in_p1 = P2.moved(cq.Location(cq.Vector(0, 0, dz_p2)))
    out = {"plates_x_mm": geo["plates"], "pin_from_joint_face_mm": PIN_FROM_FACE, "pin_dy_mm": geo["dy"],
           "P1_vs_module_mm3": overlap(P1, module), "P2_vs_module_mm3": overlap(p2_in_p1, module),
           "P1_vs_P2_at_0deg_mm3": overlap(P1, p2_in_p1)}
    def first_touch(sign, stop):
        # +X rotation carries the distal end towards -Y (palmar): flexion
        for deg in range(0, stop + 1, 2):
            loc = cq.Location(cq.Vector(0, geo["dy"], geo["pin1"]), cq.Vector(1, 0, 0), sign * deg) * \
                cq.Location(cq.Vector(0, -geo["dy"], -geo["pin1"]))
            ov = overlap(P1, p2_in_p1.moved(loc))
            if ov and ov > 0.05:
                return deg
        return None
    out["pla_parts_first_touch_flexion_deg"] = first_touch(1, 120)
    out["pla_parts_first_touch_extension_deg"] = first_touch(-1, 40)
    # hand calculations: the whole tendon squeeze through the two pins
    per_pin = SERVO_T / 2
    out["hand"] = {
        "load_per_pin_N": per_pin,
        "pla_bearing_stress_MPa": round(per_pin / (PIN_D * PLATE_T), 1),
        "pla_bearing_safety": round(PLA_BEARING / (per_pin / (PIN_D * PLATE_T)), 1),
        "plate_tear_out_stress_MPa": round(per_pin / (2 * (PLATE_R - PIN_HOLE / 2) * PLATE_T), 1),
        "steel_pin_shear_safety": round(STEEL_SHEAR / (per_pin / (math.pi * PIN_D ** 2 / 4)), 0),
        "filament_pin_1p75_shear_MPa": round(per_pin / (math.pi * 1.75 ** 2 / 4), 1),
        "pin_friction_torque_at_servo_limit_Nmm": round(FRICTION * SERVO_T * PIN_D / 2, 1),
    }
    return out


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "deep_offset" / "B5_t150_a45_deep"
    geo = build(folder)
    res = checks(geo)              # before the exports: the STL meshing upsets later booleans
    OUT.mkdir(parents=True, exist_ok=True)
    for k, name in (("P1", "02_Phalanx1_pinned"), ("P2", "04_Phalanx2_pinned")):
        cq.exporters.export(cq.Workplane().add(geo[k]), str(OUT / f"{name}.step"))
        cq.exporters.export(cq.Workplane().add(geo[k]), str(OUT / f"{name}.stl"), tolerance=0.01, angularTolerance=0.1)
    module, dz_p2 = place(geo)
    asm = cq.Compound.makeCompound([geo["P1"], module, geo["P2"].moved(cq.Location(cq.Vector(0, 0, dz_p2)))])
    cq.exporters.export(cq.Workplane().add(asm), str(OUT / "pip_assembly.step"))
    cq.exporters.export(cq.Workplane().add(asm), str(OUT / "pip_assembly.stl"), tolerance=0.02, angularTolerance=0.2)
    res["module"] = str(folder.relative_to(HERE))
    (OUT / "checks.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
