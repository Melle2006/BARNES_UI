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
ATTACH = 8.0                         # length the plate's root runs onto its phalanx
PIN_D = 2.0
#: Pin offset across the finger, mm (+Y is dorsal): the free B5's rotation pole drifts
#: palmar as it bends (round-1 FEA, about 1.1 mm by 90 deg); a pin 0.65 mm palmar of the
#: strip crossing follows it best (pinned FEA, TYPE B/analysis/results/PIP_pinned/).
PIN_DY = -0.65
PIN_HOLE = 2.05

#: Two layouts of the same hinge (see the module docstring):
#: "outside" - plates outboard of the unchanged module's collar (13.4 mm), proximal phalanx
#:             plate inner, middle phalanx plate outer, each on a tapered fin from the
#:             phalanx's side. 2.6 mm a side in round 1; slimmed to 2.05 mm here.
#: "inset"   - the module's collars cut down to 9.2 mm wide (b5_inset.py) so both plates fit
#:             inside the phalanx's own 14 mm: proximal phalanx plate outer, rising straight
#:             out of its socket wall; middle phalanx plate inner, its root jogging out onto
#:             its socket wall next to the joint face.
LAYOUTS = {
    "outside": dict(dy=-0.65, collar_half=6.7, clear=0.2, plate_t=(1.0, 1.0), gap=0.15, plate_r=4.0, outer="P2",
                    out=HERE / "pinned_b5"),
    "inset": dict(dy=-0.8, collar_half=4.6, clear=0.3, plate_t=(1.0, 1.0), gap=0.15, plate_r=3.0, outer="P1",
                  out=HERE / "pinned_b5_inset", jog=1.2, socket_half=5.8),
}

# hand calculation inputs
SERVO_T = 47.0                       # N, the servo's usable tendon tension
PLA_BEARING = 30.0                   # MPa, conservative for printed PLA
STEEL_SHEAR = 300.0                  # MPa, plain steel dowel
FRICTION = 0.3                       # PLA on steel, dry


def stadium(x0, x1, z_root, z_pin, dy, r):
    """A plate x0..x1 (x > 0; mirrored later): a bar 2r tall centred on the pin's y, from
    z_root to the pin, capped by a disc of radius r round the pin. Its edges never come
    closer to the other phalanx than r from the pin, at any angle."""
    z_lo, z_hi = sorted((z_root, z_pin))
    bar = cq.Workplane("XY").box(x1 - x0, 2 * r, z_hi - z_lo, centered=(False, True, False)).translate((x0, dy, z_lo))
    disc = cq.Workplane("YZ").workplane(offset=x0).center(dy, z_pin).circle(r).extrude(x1 - x0)
    return bar.union(disc)


def fin(x_body, x_plate, z_face, length, dy, r, towards):
    """Tapered fin joining a phalanx's side (x_body) to a plate's outer face (x_plate):
    full width at the joint face, running out to the side over `length`."""
    zs = z_face - length if towards < 0 else z_face + length
    pts = [(x_body, z_face), (x_plate, z_face), (x_body, zs)]
    w = cq.Workplane("XZ").polyline(pts).close().extrude(r, both=True)
    return w.translate((0, dy, 0))


def jogged(x0, x1, xr0, xr1, z_face, z_pin, dy, r, jog):
    """Middle phalanx inner plate (inset layout): at the pin it is x0..x1; next to the joint
    face it steps out to xr0..xr1 (onto the socket wall) over `jog` mm."""
    main = stadium(x0, x1, z_face - jog, z_pin, dy, r)
    sec = lambda a, b, z: cq.Sketch().push([((a + b) / 2, dy)]).rect(b - a, 2 * r).moved(cq.Location(cq.Vector(0, 0, z)))  # noqa: E731
    ramp = (cq.Workplane("XY").placeSketch(sec(x0, x1, z_face - jog), sec(xr0, xr1, z_face)).loft())
    root = cq.Workplane("XY").box(xr1 - xr0, 2 * r, ATTACH, centered=(False, True, False)).translate((xr0, dy, z_face))
    return main.union(ramp).union(root)


def side_extent(solid, z):
    """Half-width of the phalanx at height z (largest |x| of its section there)."""
    sec = solid.intersect(cq.Workplane("XY").box(60, 60, 0.4).translate((0, 0, z)).val())
    bb = sec.BoundingBox()
    return max(abs(bb.xmin), abs(bb.xmax))


def build(module_folder: Path, dy: float = None, layout: str = "outside", module=None):
    L = LAYOUTS[layout]
    dy = L["dy"] if dy is None else dy
    p1 = cq.importers.importStep(str(PHAL / "02_Phalanx1.step")).val()
    p2 = cq.importers.importStep(str(PHAL / "04_Phalanx2.step")).val()
    mod = module if module is not None else cq.importers.importStep(str(module_folder / "03_PIP_module.step")).val()
    z1 = p1.BoundingBox().zmax                     # P1's joint face (distal end)
    z2 = p2.BoundingBox().zmin                     # P2's joint face (proximal end)
    pin1, pin2 = z1 + PIN_FROM_FACE, z2 - PIN_FROM_FACE
    w1, w2 = side_extent(p1, z1 - 2.0), side_extent(p2, z2 + 2.0)
    r = L["plate_r"]
    ti, to = L["plate_t"]
    i0 = L["collar_half"] + L["clear"]             # inner plate
    i1 = i0 + ti
    o0 = i1 + L["gap"]                             # outer plate
    o1 = o0 + to
    parts1, parts2 = [], []
    for sx in (1, -1):
        m = (lambda w: w.mirror("YZ")) if sx < 0 else (lambda w: w)
        if layout == "outside":
            q1 = stadium(i0, i1, z1 - ATTACH, pin1, dy, r).union(fin(w1 - 0.6, i1, z1, ATTACH, dy, r, -1))
            q2 = stadium(o0, o1, z2 + ATTACH, pin2, dy, r).union(fin(w2 - 0.6, o1, z2, ATTACH, dy, r, +1))
        else:
            q1 = stadium(o0, o1, z1 - ATTACH, pin1, dy, r)
            xr0 = L["socket_half"]
            q2 = jogged(i0, i1, xr0, xr0 + ti, z2, pin2, dy, r, L["jog"])
        parts1.append(m(q1))
        parts2.append(m(q2))
    # pin holes: through both plates; on the inset layout the inner plate's hole stops
    # 0.3 mm short of its inner face so the pin cannot be pushed into the module
    stop = i0 + (0.3 if layout == "inset" else 0.0)
    hole = lambda zp: (cq.Workplane("YZ").workplane(offset=stop).center(dy, zp).circle(PIN_HOLE / 2).extrude(20)  # noqa: E731
                       .union(cq.Workplane("YZ").workplane(offset=-stop).center(dy, zp).circle(PIN_HOLE / 2).extrude(-20)))
    P1 = cq.Workplane().add(p1)
    for q in parts1:
        P1 = P1.union(q)
    P1 = P1.cut(hole(pin1))
    P2 = cq.Workplane().add(p2)
    for q in parts2:
        P2 = P2.union(q)
    P2 = P2.cut(hole(pin2))
    plates = {"P1": (o0, o1) if L["outer"] == "P1" else (i0, i1), "P2": (o0, o1) if L["outer"] == "P2" else (i0, i1)}
    return dict(P1=P1.val(), P2=P2.val(), module=mod, dy=dy, z1=z1, z2=z2, pin1=pin1, pin2=pin2, layout=layout,
                plates=plates, plate_r=r, plate_t=(ti, to), width_over_plates=round(2 * max(o1, w1, w2), 2),
                widths=(w1, w2))


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
    out = {"layout": geo["layout"], "plates_x_mm": geo["plates"], "plate_t_mm": geo["plate_t"],
           "plate_disc_r_mm": geo["plate_r"], "joint_width_over_plates_mm": geo["width_over_plates"],
           "pin_from_joint_face_mm": PIN_FROM_FACE, "pin_dy_mm": geo["dy"],
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
    PLATE_T, PLATE_R = min(geo["plate_t"]), geo["plate_r"]
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


def export(geo, out, module_name):
    out.mkdir(parents=True, exist_ok=True)
    for k, name in (("P1", "02_Phalanx1_pinned"), ("P2", "04_Phalanx2_pinned")):
        cq.exporters.export(cq.Workplane().add(geo[k]), str(out / f"{name}.step"))
        cq.exporters.export(cq.Workplane().add(geo[k]), str(out / f"{name}.stl"), tolerance=0.01, angularTolerance=0.1)
    module, dz_p2 = place(geo)
    asm = cq.Compound.makeCompound([geo["P1"], module, geo["P2"].moved(cq.Location(cq.Vector(0, 0, dz_p2)))])
    cq.exporters.export(cq.Workplane().add(asm), str(out / "pip_assembly.step"))
    cq.exporters.export(cq.Workplane().add(asm), str(out / "pip_assembly.stl"), tolerance=0.02, angularTolerance=0.2)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", choices=list(LAYOUTS), default="outside")
    ap.add_argument("--module", default=None, help="module folder (default: B5 t1.5 deep / the inset build)")
    ap.add_argument("--dy", type=float, default=None, help="pin offset (default: the layout's)")
    a = ap.parse_args()
    L = LAYOUTS[a.layout]
    folder = Path(a.module) if a.module else HERE / "deep_offset" / "B5_t150_a45_deep"
    geo = build(folder, a.dy, a.layout)
    res = checks(geo)              # before the exports: the STL meshing upsets later booleans
    export(geo, L["out"], folder.name)
    res["module"] = str(folder.resolve().relative_to(HERE))
    (L["out"] / "checks.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
