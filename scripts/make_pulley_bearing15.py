"""Rig pulley for a 5 × 15 × 5 mm ball bearing, on the printed rig's M3 axle.

    python3 scripts/make_pulley_bearing15.py         # needs trimesh, manifold3d

Replaces PUL (made for a 623ZZ, 3 × 10 × 4) on the already printed rig base. Three parts:

* PULB pulley: bore Ø15.0 press fit on the bearing's outer ring, 5.0 mm wide (the bearing's
  width, so it sits flush both sides), rim Ø20.4, 1.2 mm deep groove with sloped sides
  (1.2 mm at the bottom, 1.8 mm at the rim) for 0.5–0.8 mm line. Groove bottom Ø18.0
  leaves 1.5 mm of PLA round the bearing.
* SLV sleeve: Ø4.95 × 5.0 mm, Ø3.3 hole: fills the bearing's 5 mm bore on the M3 bolt.
* WSH washers (print 2): Ø6.5 × 0.7 mm, Ø3.3 hole: one each side between the bearing's inner
  ring and the clevis arms, so the bolt clamps only the inner ring and the 6.6 mm clevis gap
  is filled (0.7 + 5.0 + 0.7 = 6.4 mm, 0.2 mm play). Ø6.5 keeps them off the outer ring.

The rig's axle was placed for a groove bottom at r = 8.0; this groove is at r = 9.0 (the
bearing needs the room), so the line meets the groove 1.0 mm further from the axle, about
5° off straight at the post's tendon slot: a percent or two of friction, which the Setup
sheet's friction check picks up if you run it with the line through the slot.

The pulley is checked against the rig base mesh at its real axle position (no overlap).
Writes print_ready/rig/PULB_pulley_bearing15.stl, SLV_sleeve_5to3.stl, WSH_washer.stl.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

RIG = Path(__file__).resolve().parents[1] / "print_ready" / "rig"
AXLE_YZ = (4.27, -33.0)          # M3 axle on RIG_rig_base.stl, along X, clevis gap x = ±3.3
W = 5.0
R_BORE, R_RIM, R_GROOVE = 7.5, 10.2, 9.0
G_BOT, G_TOP = 1.2, 1.8


def ring(r_in, r_out, h, sections=128):
    return trimesh.creation.revolve(np.array([(r_in, 0), (r_out, 0), (r_out, h), (r_in, h), (r_in, 0)]),
                                    sections=sections)


def pulley():
    zc = W / 2
    prof = [(R_BORE, 0.0), (R_RIM, 0.0), (R_RIM, zc - G_TOP / 2), (R_GROOVE, zc - G_BOT / 2),
            (R_GROOVE, zc + G_BOT / 2), (R_RIM, zc + G_TOP / 2), (R_RIM, W), (R_BORE, W), (R_BORE, 0.0)]
    return trimesh.creation.revolve(np.array(prof), sections=180)


def clearance(p):
    """Overlap volume of the pulley, placed on the rig's axle, with the rig base."""
    rig = trimesh.load(RIG / "RIG_rig_base.stl")
    q = p.copy()
    q.apply_translation([0, 0, -W / 2])
    q.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))   # axis Z -> X
    q.apply_translation([0, *AXLE_YZ])
    inter = trimesh.boolean.intersection([rig, q], engine="manifold")
    gap = rig.nearest.on_surface(q.vertices)[1].min()
    return (inter.volume if not inter.is_empty else 0.0), gap, q.bounds[:, 0]


def main():
    p = pulley()
    parts = {"PULB_pulley_bearing15.stl": p, "SLV_sleeve_5to3.stl": ring(1.65, 2.475, 5.0),
             "WSH_washer.stl": ring(1.65, 3.25, 0.7)}
    for name, m in parts.items():
        assert m.is_watertight and m.is_volume, name
        m.export(RIG / name)
        print(f"wrote {name}: {m.extents.round(2)} mm, {m.volume:.0f} mm³")
    vol, gap, xs = clearance(p)
    print(f"pulley vs rig base: overlap {vol:.3f} mm³, nearest {gap:.2f} mm, pulley spans x {xs.round(2)}")
    assert vol < 1e-3
    print(f"line offset {R_GROOVE - 8.0:.1f} mm -> {np.degrees(np.arctan2(R_GROOVE - 8.0, 11.0)):.0f}° at the post slot")


if __name__ == "__main__":
    main()
