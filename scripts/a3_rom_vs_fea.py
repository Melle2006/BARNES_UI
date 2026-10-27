"""Compare the reduced-order and FEA stiffness of the A3 flexure, like for like.

Why this script exists, and what it corrects
---------------------------------------------

Phase 3 criterion 7 reported that the reduced-order model overstates the A3 twin
strap's rotational stiffness by 23.8 % -- 7.558 against 6.103 N.mm/rad. Neither half
of that comparison was reproducible: both came from ad-hoc sessions, and the two
settings that matter most to the answer were never written down.

They matter a great deal. Measured here:

* **Joint axis height.** The reduced-order stiffness at the bounding box centre
  (z = 7.42 mm) is 3.16 N.mm/rad; at the collar's mounting-feature height
  (z = 5.44 mm) it is 6.86. A two-millimetre shift more than doubles it.
* **Where the member is taken to be clamped.** Extracting the straps between
  y = 30.60 and 59.26 gives 6.56 N.mm/rad; moving each end 0.15 mm inward gives 6.90;
  3.4 mm from each end gives 6.86 and 4.5 mm gives 9.93.

The 7.558 figure corresponds to a free length roughly half a millimetre shorter at
each end than the FEA's clamp line. A shorter member is a stiffer member, so a good
part of the reported 23.8 % was the two halves measuring different spans rather than
the beam idealisation being wrong.

What this script does instead is compute the reduced-order stiffness **at the FEA's
own axis and its own clamp line**, and report the comparison with the boundary
sensitivity attached, because that sensitivity is larger than the figure deserves to
be quoted to.

What it cannot remove
---------------------

A strap root blends into a collar; there is no sharp clamp line. The FEA fixes every
surface wholly inside the attachment depth and leaves straddling surfaces free, so
its effective boundary is somewhere in a band rather than at a plane. The comparison
therefore carries a few per cent of irreducible uncertainty from that definition
alone, and this script reports a range rather than pretending otherwise.

    python scripts/a3_rom_vs_fea.py --step <A3 .step> --fea-stiffness 6.10336
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a3_joint_stiffness import (  # noqa: E402
    AXIS_POINT_MM,
    COLLAR_DEPTH_MM,
    PROVISIONAL_MODULUS_MPA,
)

from barnes_ui.core.cad.registry import load_geometry  # noqa: E402
from barnes_ui.core.flexure import CenterlineError, extract_members  # noqa: E402
from barnes_ui.core.material import provisional_tpu  # noqa: E402
from barnes_ui.core.mechanics import JointAxis, analyse_joint_flexure  # noqa: E402

#: How far inside the collar faces to take the clamp line, in mm.
#:
#: The FEA fixes every surface wholly within COLLAR_DEPTH_MM of each end, so the
#: straps are free from about 3.16 mm inward. The centreline extractor refuses to
#: start exactly there -- the collar's internal features make the cross-section count
#: vary along the sweep, which is a guard working correctly rather than a nuisance --
#: so the comparison is made at a few offsets just inside it and reported as a band.
CLAMP_OFFSETS_MM = (0.10, 0.15, 0.25, 0.40)

#: Angle the comparison is made at, in degrees. Matches the FEA run.
COMPARISON_ANGLE_DEG = 2.0


def reduced_order_stiffness(shape, start: float, end: float, axis: JointAxis,
                            modulus: float) -> tuple[float, float]:
    """Reduced-order rotational stiffness over one clamp span. Returns (K, arc)."""
    members = extract_members(
        shape, sweep_axis=(0, 1, 0), bending_axis=(1, 0, 0),
        start=start, end=end, samples=80,
    )
    _, stiffness = analyse_joint_flexure(
        members, provisional_tpu(modulus), axis,
        max_angle_rad=np.radians(90.0), steps=10,
    )
    return stiffness.rotational_stiffness, members[0].arc_length


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument(
        "--fea-stiffness", type=float, required=True,
        help="Rotational stiffness from the FEA, N.mm/rad, at the same axis.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    model = load_geometry(args.step)
    solid = model.solids[0]
    box = solid.bounding_box
    axis = JointAxis(origin=AXIS_POINT_MM, direction=(1.0, 0.0, 0.0))

    # The collar faces, which is where the FEA's fixed region actually ends.
    proximal_face = box.ymin + COLLAR_DEPTH_MM
    distal_face = box.ymax - COLLAR_DEPTH_MM

    rows = []
    for offset in CLAMP_OFFSETS_MM:
        start = proximal_face + offset
        end = distal_face - offset
        try:
            stiffness, arc = reduced_order_stiffness(
                solid.shape, start, end, axis, PROVISIONAL_MODULUS_MPA
            )
        except CenterlineError as exc:
            rows.append({
                "offset_mm": offset, "refused": str(exc).split(".")[0],
            })
            continue
        rows.append({
            "offset_mm": offset,
            "clamp_from_mm": start,
            "clamp_to_mm": end,
            "arc_length_mm": arc,
            "reduced_order_n_mm_per_rad": stiffness,
            "ratio_to_fea": stiffness / args.fea_stiffness,
        })

    usable = [r for r in rows if "ratio_to_fea" in r]
    if not usable:
        raise SystemExit(
            "The centreline extractor refused every clamp offset tried. The collar "
            "features reach further in than CLAMP_OFFSETS_MM allows for."
        )
    ratios = [r["ratio_to_fea"] for r in usable]

    summary = {
        "fea_stiffness_n_mm_per_rad": args.fea_stiffness,
        "axis_point_mm": list(AXIS_POINT_MM),
        "comparison_angle_deg": COMPARISON_ANGLE_DEG,
        "provisional_modulus_mpa": PROVISIONAL_MODULUS_MPA,
        "clamp_band": rows,
        "ratio_min": min(ratios),
        "ratio_max": max(ratios),
        "overstatement_percent_min": (min(ratios) - 1.0) * 100.0,
        "overstatement_percent_max": (max(ratios) - 1.0) * 100.0,
    }

    print(f"FEA stiffness          {args.fea_stiffness:.6g} N.mm/rad")
    print(f"joint axis             {AXIS_POINT_MM}")
    print()
    print(f"{'offset':>8}{'clamp span':>24}{'arc':>10}{'ROM':>11}{'ROM/FEA':>10}")
    for row in rows:
        if "ratio_to_fea" not in row:
            print(f"{row['offset_mm']:8.2f}  REFUSED: {row['refused']}")
            continue
        print(
            f"{row['offset_mm']:8.2f}"
            f"{row['clamp_from_mm']:11.3f} to {row['clamp_to_mm']:8.3f}"
            f"{row['arc_length_mm']:10.4f}"
            f"{row['reduced_order_n_mm_per_rad']:11.5g}"
            f"{row['ratio_to_fea']:10.4f}"
        )
    print()
    print(
        f"The reduced-order model overstates the FEA by "
        f"{summary['overstatement_percent_min']:.1f} % to "
        f"{summary['overstatement_percent_max']:.1f} %, depending on where the "
        "clamp line is taken."
    )
    print(
        "That spread is the honest precision of this comparison. A strap root blends "
        "into a collar, so there is no plane at which the member becomes free, and "
        "the FEA's own boundary is a band rather than a line."
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
