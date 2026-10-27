"""Mesh-convergence study of the A3 twin-strap joint stiffness.

Why this exists
---------------

Phase 3 criterion 3 was met with a mesh study on a *cantilever benchmark*, not on the
flexure's rotational stiffness. The 6.103 N.mm/rad figure that the headline 24 % result
rests on therefore came from a single mesh and carried an unknown discretisation error,
flagged as ``CAVEAT_NO_MESH_STUDY``. This script removes that caveat, or confirms that
it was justified.

The refinement parameter is the number of second-order tetrahedra across the strap's
1.0 mm thickness, which is the feature that controls bending accuracy. The element size
is therefore ``1.0 / n`` mm.

Each solve writes its own JSON as soon as it finishes, so a study interrupted part-way
still leaves usable evidence rather than nothing.

    python scripts/a3_mesh_study.py --step <A3 .step> --refinements 1 2 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a3_joint_stiffness import SMALLEST_FEATURE_MM, build_and_run  # noqa: E402

from barnes_ui.core.fea.convergence import run_mesh_convergence  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument("--refinements", type=int, nargs="+", default=[1, 2, 3],
                        help="Elements across the 1.0 mm strap thickness.")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Directory for the per-mesh JSON files and the summary.")
    parser.add_argument("--timeout", type=float, default=36000.0)
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    def solve_at(n: int) -> tuple[float, int, int, float]:
        size = SMALLEST_FEATURE_MM / n
        summary = build_and_run(args.step, size, archive_root=None,
                                timeout=args.timeout)
        (args.out_dir / f"mesh_{n}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        stiffness = summary.get("stiffness_n_mm_per_rad")
        if stiffness is None:
            raise SystemExit(
                f"The {size:g} mm mesh produced no usable stiffness: "
                f"{summary.get('failure', 'unknown failure')}. "
                "A failed solve is not a convergence point and will not be invented."
            )
        print(f"n={n}  size={size:.4g} mm  elements={summary['element_count']}  "
              f"K={stiffness:.6g} N.mm/rad  ({summary['wall_seconds']:.0f} s, "
              f"{summary['cutbacks']} cutbacks)", flush=True)
        # Degrees of freedom: three per node, before constraints.
        return stiffness, summary["element_count"], 3 * summary["node_count"], size

    study = run_mesh_convergence(
        solve_at,
        refinements=args.refinements,
        quantity="A3 joint rotational stiffness",
        unit="N.mm/rad",
    )

    print(study.summary(), flush=True)
    for note in study.notes:
        print(f"NOTE: {note}", flush=True)

    (args.out_dir / "study.json").write_text(
        json.dumps(
            {
                "quantity": study.quantity,
                "unit": study.unit,
                "points": [
                    {
                        "elements_through_thickness": p.elements_through_thickness,
                        "element_size_mm": p.element_size,
                        "element_count": p.element_count,
                        "degrees_of_freedom": p.degrees_of_freedom,
                        "stiffness_n_mm_per_rad": p.value,
                    }
                    for p in study.points
                ],
                "final_change_fraction": study.final_change,
                "converged_2pc": study.is_converged(),
                "monotonic": study.is_monotonic(),
                "richardson_estimate": study.richardson_estimate(),
                "notes": study.notes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
