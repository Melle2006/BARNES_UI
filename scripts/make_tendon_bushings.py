"""Tendon bushings: hold the line on the centre of the 3 mm tendon channel at the PIP.

    python3 scripts/make_tendon_bushings.py        # needs trimesh, manifold3d

The modules' tendon channel is Ø3.0 for a 0.5-0.8 mm line, so under load the line drifts to
the channel's joint-side wall and the tendon's lever at the PIP drops by up to about 1 mm
(seen on the rig in step 2). The lever is set where the line leaves the two collars into the
flex zone. A bushing pressed into the channel at each of those two mouths holds the line
within 0.2-0.3 mm of the channel centre, which is the lever the analyses use.

Bushing: Ø3.1 (snug in the TPU channel, which stretches) or Ø2.9 (if 3.1 is too tight),
bore Ø1.2 with a 0.3 mm rounded-off lead at both ends so the line slides and bends over a
smooth edge, 3.0 mm long (through the 0.8 mm collar into the tab's channel). Push it in from
the flex-zone side with a 1.75 mm filament end until flush with the collar face.

Writes print_ready/plates/tendon_bushings_plate.stl: 12 of each size (2 per module).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

OUT = Path(__file__).resolve().parents[1] / "print_ready" / "plates" / "tendon_bushings_plate.stl"
L, BORE, LEAD = 3.0, 1.2, 0.3
SIZES = (3.1, 2.9)
N = 12


def bushing(od):
    r, b = od / 2, BORE / 2
    # revolve a profile: outer wall straight, bore with a conical lead-in at both ends
    prof = [(b + LEAD, 0.0), (r, 0.0), (r, L), (b + LEAD, L), (b, L - LEAD), (b, LEAD), (b + LEAD, 0.0)]
    m = trimesh.creation.revolve(np.array(prof), sections=72)
    m.apply_translation(-m.bounds[0] * [0, 0, 1])
    return m


def main():
    parts = []
    for row, od in enumerate(SIZES):
        for k in range(N):
            m = bushing(od)
            m.apply_translation([k * 6.0, row * 8.0, 0])
            parts.append(m)
    assert all(p.is_watertight and p.is_volume for p in parts)
    t = trimesh.util.concatenate(parts)
    t.apply_translation([128 - t.bounds[:, 0].mean(), 128 - t.bounds[:, 1].mean(), 0])
    t.export(OUT)
    print(f"wrote {OUT.name}: {len(parts)} bushings, {t.extents.round(1)} mm")


if __name__ == "__main__":
    main()
