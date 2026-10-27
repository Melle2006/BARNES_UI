"""Reproduce the A3 twin-strap joint-stiffness FEA run at a chosen mesh density.

Why this script exists
----------------------

The headline Phase 3 number -- the reduced-order model overstates the A3 flexure's
rotational stiffness by 24 per cent -- was first produced by an ad-hoc sequence of
calls that was not saved. That is a reproducibility hole: the figure is in the
documentation, the run archive is in one machine's temp directory, and nobody else
could regenerate it.

This closes that hole and doubles as the driver for the mesh-convergence study the
original result was missing. The analysis itself lives in
``barnes_ui.core.fea.joint_stiffness`` -- it is shared with the GUI, and a
boundary-condition recipe that took two wrong answers to get right should exist once.
What is here is the part specific to this file: which numbers describe the A3 part,
and why each of them has the value it does.

Usage
-----

    python scripts/a3_joint_stiffness.py --step <path to A3 .step> --element-size 0.5

Writes a JSON summary and prints it. Several invocations at different element sizes
form a convergence study; ``scripts/a3_mesh_study.py`` orchestrates that.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.cad.registry import load_geometry  # noqa: E402
from barnes_ui.core.fea.joint_stiffness import (  # noqa: E402
    JointStiffnessSetup,
    measure_joint_stiffness,
)
from barnes_ui.core.fea.solver import find_solver, probe_solver  # noqa: E402
from barnes_ui.core.material.models import provisional_tpu  # noqa: E402

#: Depth of each PIP collar measured along the part's long (Y) axis, in mm.
#:
#: Measured from the imported solid: the part spans 27.347 to 62.523 mm in Y, the
#: proximal collar ends at Y = 30.5 and the distal collar begins at Y = 59.36. Both
#: are therefore a little over 3.1 mm deep. 3.2 mm selects the whole collar and no
#: part of a strap; the strap roots start immediately beyond it.
COLLAR_DEPTH_MM = 3.2

#: The part spans between its collars along Y.
SPAN_AXIS = 1

#: Joint rotation applied, in degrees. See JointStiffnessSetup for why it is small.
ROTATION_DEG = 2.0

#: The strap is 1.0 mm thick and the collar wall 1.2 mm, both interior. The default
#: element size comes from the bounding box's smallest extent, which for this part is
#: 10.95 mm -- giving 5.48 mm elements, which CalculiX rejected outright.
SMALLEST_FEATURE_MM = 1.0

#: Provisional modulus, in MPa. NOT a calibrated TPU property.
#:
#: The stiffness *ratio* this script exists to feed is independent of it: both the
#: reduced-order model and a Neo-Hookean FEA at small strain are linear in E, so the
#: modulus cancels. The absolute torque is not independent of it and must not be
#: quoted.
PROVISIONAL_MODULUS_MPA = 12.0


def build_and_run(step_path: Path, element_size: float, archive_root: Path | None,
                  timeout: float) -> dict:
    """Mesh, submit and parse one A3 analysis. Returns a JSON-serialisable summary."""
    model = load_geometry(step_path)
    if model.solid_count != 1:
        raise SystemExit(
            f"Expected a single solid in {step_path.name}, found {model.solid_count}. "
            "This script models the flexure as one body."
        )
    solid = model.solids[0]

    solver = find_solver()
    if solver is None:
        raise SystemExit(
            "CalculiX was not found. See docs/08-calculix-installation.md. This "
            "script does not fall back to the reduced-order model."
        )
    solver = probe_solver(solver)

    setup = JointStiffnessSetup(
        attachment_depth=COLLAR_DEPTH_MM,
        rotation_deg=ROTATION_DEG,
        span_axis=SPAN_AXIS,
        joint_direction=(1.0, 0.0, 0.0),
        # axis_point left at the default: the A3's straps arch symmetrically about
        # the centre of its envelope, so the two coincide here. On a part where they
        # do not, the axis is a user input and must not be inferred -- risk R4.
        smallest_feature=SMALLEST_FEATURE_MM,
        element_size=element_size,
        second_order=True,
    )
    material = provisional_tpu(PROVISIONAL_MODULUS_MPA)

    started = time.perf_counter()
    outcome = measure_joint_stiffness(
        solid.shape, material, setup, solver,
        archive_directory=archive_root, timeout=timeout,
        title=f"A3 twin strap, {ROTATION_DEG} deg joint rotation, "
              f"{element_size:g} mm elements",
    )
    wall = time.perf_counter() - started

    summary = {
        "element_size_mm": element_size,
        "element_count": int(outcome.mesh.element_count),
        "node_count": int(outcome.mesh.node_count),
        "element_type": outcome.mesh.calculix_element_type,
        "proximal_surface_sets": len(outcome.proximal_sets),
        "distal_surface_sets": len(outcome.distal_sets),
        "axis_point_mm": list(outcome.axis_point),
        "rotation_deg": ROTATION_DEG,
        "converged": bool(outcome.result.convergence.converged),
        "increments_completed": int(outcome.result.convergence.increments_completed),
        "cutbacks": int(outcome.result.convergence.cutbacks),
        "null_solution": bool(outcome.result.is_null_solution),
        "trustworthy": bool(outcome.result.is_trustworthy),
        "wall_seconds": round(wall, 1),
        "run_directory": (
            str(outcome.result.run_directory) if outcome.result.run_directory else None
        ),
        "provisional_modulus_mpa": PROVISIONAL_MODULUS_MPA,
        "torque_n_mm": outcome.torque,
        "stiffness_n_mm_per_rad": outcome.stiffness,
        "notes": list(outcome.notes),
    }
    if outcome.failure:
        summary["failure"] = outcome.failure
    if outcome.succeeded:
        summary["reactions"] = {
            name: [float(x) for x in value]
            for name, value in outcome.result.reaction_forces.items()
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", type=Path, required=True,
                        help="Path to the A3 twin-strap STEP file.")
    parser.add_argument("--element-size", type=float, default=0.5,
                        help="Target element size in mm (default 0.5).")
    parser.add_argument("--archive", type=Path, default=None,
                        help="Directory to archive the run into.")
    parser.add_argument("--timeout", type=float, default=14400.0,
                        help="Solver time limit in seconds (default 4 hours).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write the JSON summary here as well as to stdout.")
    args = parser.parse_args(argv)

    summary = build_and_run(args.step, args.element_size, args.archive, args.timeout)
    text = json.dumps(summary, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0 if summary.get("stiffness_n_mm_per_rad") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
