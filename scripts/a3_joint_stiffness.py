"""Reproduce the A3 twin-strap joint-stiffness FEA run at a chosen mesh density.

Why this script exists
----------------------

The headline Phase 3 number -- the reduced-order model overstates the A3 flexure's
rotational stiffness by 24 % -- was first produced by an ad-hoc sequence of calls that
was not saved. That is a reproducibility hole: the figure is in the documentation, the
run archive is on one machine's temp directory, and nobody else could regenerate it.

This script closes that hole and does double duty as the driver for the mesh-convergence
study that the original result was missing. Everything that defines the analysis is a
named constant below, with the reasoning for its value, so a reader can disagree with a
modelling choice by reading rather than by guessing.

Usage
-----

    python scripts/a3_joint_stiffness.py --step <path to A3 .step> --element-size 0.5

Writes a JSON summary next to the run archive and prints it. Several invocations at
different element sizes form a convergence study; ``scripts/a3_mesh_study.py``
orchestrates that and does the Richardson extrapolation.

What the model is
-----------------

The proximal collar is fully fixed. The distal collar is tied into a rigid body whose
reference node sits on the joint axis, and that reference node is rotated through a
small angle about the axis. The reaction moment reported at the rotation node, divided
by the angle, is the joint's rotational stiffness.

Two boundary-condition mistakes produced plausible-looking wrong answers before this
configuration was settled, and both are worth knowing about:

* Tying only one of the distal collar's 62 surfaces into the rigid body left the rest of
  the collar free, so the "rigid" body was a single patch dragging a deformable shell.
  Result: 62.8x the reduced-order stiffness.
* Leaving the reference node's translations free let the collar drift sideways instead of
  rotating about the axis. Result: 55.4x. The run converged, raised no warnings, and had
  a perfectly linear reaction history. The only symptom was an implausible cutback count.

Both are now structural: every surface inside the collar depth is tied, and
``RigidBody.pin_reference`` defaults to True.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.cad.registry import load_geometry  # noqa: E402
from barnes_ui.core.fea.deck import (  # noqa: E402
    BoundaryCondition,
    DeckSettings,
    RigidBody,
    write_deck,
)
from barnes_ui.core.fea.meshing import MeshSettings, generate_mesh  # noqa: E402
from barnes_ui.core.fea.runner import run_analysis  # noqa: E402
from barnes_ui.core.fea.solver import find_solver, probe_solver  # noqa: E402
from barnes_ui.core.material.models import provisional_tpu  # noqa: E402

#: Depth of each PIP collar measured along the part's long (Y) axis, in mm.
#:
#: Measured from the imported solid: the part spans 27.347 to 62.523 mm in Y, the
#: proximal collar ends at Y = 30.5 and the distal collar begins at Y = 59.36. Both
#: collars are therefore a little over 3.1 mm deep. 3.2 mm selects the whole collar and
#: no part of a strap; the straps' roots start immediately beyond it.
COLLAR_DEPTH_MM = 3.2

#: Joint rotation applied, in degrees.
#:
#: Deliberately small. The reduced-order model is a tangent stiffness at the neutral
#: position and linear by construction, so comparing at a large angle would conflate the
#: beam idealisation (what we want to measure) with the linear-kinematics extrapolation
#: (a separate question). At 2 degrees both models are inside the regime the fast one
#: claims to describe.
ROTATION_DEG = 2.0

#: The strap is 1.0 mm thick and the collar wall 1.2 mm, and both are interior features.
#: The default element size derives from the bounding box's smallest extent, which for
#: this part is 10.95 mm -- giving 5.48 mm elements, which CalculiX rejected outright.
#: The thinnest feature has to be stated explicitly.
SMALLEST_FEATURE_MM = 1.0

#: Provisional modulus, in MPa. NOT a calibrated TPU property.
#:
#: The stiffness ratio this script exists to measure is independent of it -- both the
#: reduced-order model and a Neo-Hookean FEA at small strain are linear in E, so the
#: modulus cancels out of the ratio. The absolute torque is not independent of it and
#: must not be quoted.
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
    box = solid.bounding_box

    y_proximal = box.ymin + COLLAR_DEPTH_MM
    y_distal = box.ymax - COLLAR_DEPTH_MM
    if y_proximal >= y_distal:
        raise SystemExit(
            f"The two {COLLAR_DEPTH_MM} mm collars overlap in a part only "
            f"{box.ymax - box.ymin:.2f} mm long. Wrong file?"
        )

    # The joint axis runs along X through the centre of the part's envelope. For this
    # flexure the straps arch symmetrically about that line, which is why the centre of
    # the bounding box and the centre of rotation coincide. On a part where they do not,
    # the axis is a user input and must not be inferred -- see risk R4.
    axis_point = (
        0.5 * (box.xmin + box.xmax),
        0.5 * (box.ymin + box.ymax),
        0.5 * (box.zmin + box.zmax),
    )

    mesh = generate_mesh(
        solid.shape,
        MeshSettings(element_size=element_size, second_order=True),
        smallest_dimension=SMALLEST_FEATURE_MM,
    )

    proximal, distal = _classify_surfaces(mesh, y_proximal, y_distal)
    if not proximal or not distal:
        raise SystemExit(
            f"Surface classification found {len(proximal)} proximal and {len(distal)} "
            "distal surface sets. Both must be non-empty."
        )

    boundary = [
        BoundaryCondition(name, (1, 2, 3), 0.0, "proximal collar fixed")
        for name in proximal
    ]

    rigid = RigidBody(
        node_sets=distal,
        reference_point=axis_point,
        name="distal",
        pin_reference=True,
    )
    settings = DeckSettings(
        nlgeom=True,
        rigid_bodies=[rigid],
        reaction_sets=[rigid.rotation_set_name, rigid.reference_set_name],
    )
    # The rotation is applied to the rigid body's rotation node, whose DOFs 1-3 are
    # rotations about X, Y and Z. DOF 1 is the joint axis.
    boundary.append(
        BoundaryCondition(
            rigid.rotation_set_name,
            (1,),
            math.radians(ROTATION_DEG),
            f"prescribed joint rotation {ROTATION_DEG} deg about X",
        )
    )

    material = provisional_tpu(PROVISIONAL_MODULUS_MPA)
    deck = write_deck(
        mesh, material, boundary, settings,
        title=f"A3 twin strap, {ROTATION_DEG} deg joint rotation, "
              f"{element_size:g} mm elements",
    )

    solver = find_solver()
    if solver is None:
        raise SystemExit(
            "CalculiX was not found. See docs/08-calculix-installation.md. This script "
            "does not fall back to the reduced-order model."
        )
    solver = probe_solver(solver)

    started = time.perf_counter()
    result = run_analysis(
        deck, mesh, material, solver,
        archive_directory=archive_root,
        timeout=timeout,
    )
    wall = time.perf_counter() - started

    return _summarise(result, mesh, element_size, wall, axis_point,
                      len(proximal), len(distal))


def _classify_surfaces(mesh, y_proximal: float, y_distal: float
                       ) -> tuple[list[str], list[str]]:
    """Split the mesh's surface node sets into the two collars.

    A surface counts as proximal only if *every* one of its nodes lies within the
    proximal collar, and likewise for distal. A surface straddling a boundary belongs to
    neither and is left free, which is the correct treatment for the strap roots.
    """
    proximal: list[str] = []
    distal: list[str] = []
    for name, indices in mesh.node_sets.items():
        y = mesh.nodes[indices, 1]
        if y.max() <= y_proximal:
            proximal.append(name)
        elif y.min() >= y_distal:
            distal.append(name)
    return sorted(proximal), sorted(distal)


def _summarise(result, mesh, element_size: float, wall: float,
               axis_point: tuple[float, float, float],
               n_proximal: int, n_distal: int) -> dict:
    angle_rad = math.radians(ROTATION_DEG)
    rotation_set = "distal_rot"

    summary = {
        "element_size_mm": element_size,
        "element_count": int(mesh.element_count),
        "node_count": int(mesh.node_count),
        "element_type": mesh.calculix_element_type,
        "proximal_surface_sets": n_proximal,
        "distal_surface_sets": n_distal,
        "axis_point_mm": list(axis_point),
        "rotation_deg": ROTATION_DEG,
        "converged": bool(result.convergence.converged),
        "increments_completed": int(result.convergence.increments_completed),
        "cutbacks": int(result.convergence.cutbacks),
        "null_solution": bool(result.is_null_solution),
        "trustworthy": bool(result.is_trustworthy),
        "wall_seconds": round(wall, 1),
        "run_directory": str(result.run_directory) if result.run_directory else None,
        "provisional_modulus_mpa": PROVISIONAL_MODULUS_MPA,
    }

    if not result.is_trustworthy:
        summary["torque_n_mm"] = None
        summary["stiffness_n_mm_per_rad"] = None
        summary["failure"] = result.convergence.summary
        return summary

    reaction = result.reaction_forces.get(rotation_set)
    if reaction is None:
        summary["torque_n_mm"] = None
        summary["stiffness_n_mm_per_rad"] = None
        summary["failure"] = (
            f"No reaction reported for node set {rotation_set!r}. Reported sets: "
            f"{sorted(result.reaction_forces)}"
        )
        return summary

    # On a rigid body's rotation node CalculiX reports moments in the force slots, so
    # component 0 is the moment about X -- the joint axis.
    torque = float(np.asarray(reaction)[0])
    summary["torque_n_mm"] = torque
    summary["stiffness_n_mm_per_rad"] = torque / angle_rad
    summary["reactions"] = {k: [float(x) for x in np.asarray(v)]
                            for k, v in result.reaction_forces.items()}
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
