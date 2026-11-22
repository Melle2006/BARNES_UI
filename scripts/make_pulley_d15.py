"""15 mm rig pulley: a drop-in for the 20 mm PUL on the already printed rig base.

    python3 scripts/make_pulley_d15.py         # needs trimesh

Same width (6.0 mm, fits the 6.6 mm clevis) and the same bore (Ø10.1 mm, press fit for a
623ZZ bearing 3 × 10 × 4 mm on the M3 axle). Only the outside changes: rim Ø15.0 mm, a
1.2 mm deep groove with sloped sides (1.2 mm wide at the bottom, 1.8 mm at the rim) for
0.5–0.8 mm braided line. The groove bottom is at r = 6.3 mm, leaving 1.25 mm of PLA round
the bearing.

The axle on the rig was placed for the 20 mm pulley's groove (r = 8.0), so the line now
meets the groove 1.7 mm closer to the axle: it leaves the post's tendon slot about 9° off
straight. That adds roughly 2-3 % friction at the slot edge; the Setup sheet's friction check
does not see it, so run that check with the line through the slot (see the note printed).

Writes print_ready/rig/PUL15_pulley_d15.stl.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

OUT = Path(__file__).resolve().parents[1] / "print_ready" / "rig" / "PUL15_pulley_d15.stl"
W = 6.0          # axial width
R_BORE = 5.05    # Ø10.1 for the 623ZZ outer ring
R_RIM = 7.5      # Ø15
R_GROOVE = 6.3   # groove bottom
G_BOT, G_TOP = 1.2, 1.8   # groove width at the bottom / at the rim
R_TENDON_OLD = 8.0


def pulley():
    zc = W / 2
    prof = [(R_BORE, 0.0), (R_RIM, 0.0), (R_RIM, zc - G_TOP / 2), (R_GROOVE, zc - G_BOT / 2),
            (R_GROOVE, zc + G_BOT / 2), (R_RIM, zc + G_TOP / 2), (R_RIM, W), (R_BORE, W), (R_BORE, 0.0)]
    m = trimesh.creation.revolve(np.array(prof), sections=180)
    # revolve axis is Z; lay it flat (axis vertical = Z is already the print orientation: flat on the bed)
    m.apply_translation(-m.bounds[0] * [0, 0, 1])
    return m


def main():
    m = pulley()
    assert m.is_watertight and m.is_volume, "mesh not closed"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.export(OUT)
    off = R_TENDON_OLD - R_GROOVE
    ang = np.degrees(np.arctan2(off, 11.0))          # post bottom (z = -22) to axle (z = -33)
    print(f"wrote {OUT}")
    print(f"Ø{2 * R_RIM:.1f} × {W:.1f} mm, bore Ø{2 * R_BORE:.2f}, groove bottom Ø{2 * R_GROOVE:.1f}, "
          f"wall round bearing {R_GROOVE - R_BORE:.2f} mm, volume {m.volume:.0f} mm³")
    print(f"line offset from the old tangent {off:.1f} mm -> about {ang:.0f}° deflection at the post slot")


if __name__ == "__main__":
    main()
