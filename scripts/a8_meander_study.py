"""Torque-angle study of the A8 PIP meander family in TPU 90A, by nonlinear FEA.

Why this script exists
----------------------

The A8 strip is the restoring spring across the PIP joint: the finger flexes, the
strip deforms, and the stored energy brings the finger back. The three SolidWorks
exports (2-turn, 3-turn, and a 3-turn with a more arched spine) raise two design
questions -- how many turns, and how much spine curvature -- and this script answers
them the same way for every candidate, so the candidates can be compared:

1. Analyse the exported strips themselves, from their STEP files.
2. Rebuild each from :mod:`barnes_ui.core.flexure.templates.a8_meander` and check
   the replica against the export by FEA as well as by geometry.
3. Sweep spine sagitta for 2-, 3- and 4-turn strips and analyse every variant.

Each analysis drives the distal end of the strip through the full flexion range
about the joint axis, with the proximal end held, and records the reaction moment at
every increment -- a torque-angle curve, not a single stiffness -- together with the
peak strain, the strip's lowest point relative to the joint axis and its lateral
spread, which together decide whether a candidate is usable on a finger.

Boundary conditions and the assumptions inside them
---------------------------------------------------

* **Only the strip is modelled.** Both rings are treated as rigid: the proximal end
  cap is fixed and the distal end cap is tied to a rigid body that rotates about the
  joint axis. Ring compliance would make every strip slightly softer by the same
  mechanism, so it shifts absolute torque more than ranking.
* **The joint axis is assumed**, not read from the file -- STEP carries no mates.
  It is taken parallel to X through the ring centreline (z = 0) midway between the
  ring faces (y = 15.905). ``--axis-y`` and ``--axis-z`` move it, and the
  ``axis_sensitivity`` group reruns the selected design at shifted axes so the effect
  is measured rather than guessed.
* **Flexion is rotation about +X by a negative angle**, carrying the distal ring
  towards -Z, away from the side the strip sits on. That makes the strip dorsal, which
  is what a spring-back element across a finger joint has to be.
* **TPU 90A is a Neo-Hookean solid with E = 19.3 MPa** -- the 2800 psi tensile
  modulus on Jabil's TPU 90A datasheet (ASTM D638, XY coupons). It is a datasheet
  figure for one filament, not a test of the filament that will be printed, so every
  torque here is tagged as derived from a datasheet. Other 90A filaments imply about
  12 MPa (Polymaker PolyFlex TPU90, from its 100 % modulus). Torque is close to
  linear in E at the strains found here, so a different modulus rescales the
  matrices without reordering them.

Usage
-----

    python scripts/a8_meander_study.py --steps-dir <folder with the three STEP files>
        --out results/a8_meander_study [--groups exports,replicas,sweep]

Each run is written to ``<out>/runs/<label>.json`` as soon as it finishes, and a run
whose JSON already exists is skipped, so an interrupted study resumes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.cad.inspect import bounding_box  # noqa: E402
from barnes_ui.core.cad.registry import load_geometry  # noqa: E402
from barnes_ui.core.fea.contact import (  # noqa: E402
    ContactPair,
    ContactSurface,
    SurfaceType,
)
from barnes_ui.core.fea.deck import (  # noqa: E402
    BoundaryCondition,
    DeckSettings,
    RigidBody,
    write_deck,
)
from barnes_ui.core.fea.meshing import Mesh, MeshSettings, generate_mesh  # noqa: E402
from barnes_ui.core.fea.results import parse_dat_reaction_history  # noqa: E402
from barnes_ui.core.fea.runner import run_analysis  # noqa: E402
from barnes_ui.core.fea.solver import find_solver, probe_solver  # noqa: E402
from barnes_ui.core.flexure.templates.a8_meander import (  # noqa: E402
    A8_MEASURED_SAGITTA,
    A8_PLAN_2TURN,
    A8_PLAN_3TURN,
    A8MeanderParameters,
    build_a8_meander,
    sine_plan,
)
from barnes_ui.core.material.models import (  # noqa: E402
    CAVEAT_DATASHEET_DERIVED,
    HyperelasticModel,
    MaterialModelKind,
)
from barnes_ui.core.provenance import Provenance  # noqa: E402

#: Jabil TPU 90A datasheet tensile modulus, 2800 psi, in MPa.
TPU90A_MODULUS_MPA = 2800 * 0.006894757
TPU90A_POISSON = 0.49

#: Joint axis: parallel to X, through the ring centreline, midway between ring faces.
AXIS_Y_MM = 15.905
AXIS_Z_MM = 0.0

#: The proximal link's head, which the strip has to ride over in flexion: a rigid
#: cylinder about the joint axis. The proximal ring's opening is 7.0 mm tall, so the
#: link is 3.5 mm above its centreline and its rounded head can be no taller; 3.4 mm
#: allows for the rounding. The 2-turn export clears it by 0.05 mm at rest, so a
#: radius of exactly 3.5 would have the as-drawn part start in contact.
KNUCKLE_RADIUS_MM = 3.4
KNUCKLE_WALL_MM = 0.6
KNUCKLE_HALF_LENGTH_MM = 7.0
KNUCKLE_ELEMENT_MM = 1.0

#: Full flexion analysed, degrees. docs/06 gives 0 to 100 as the PIP placeholder;
#: 90 is reported as the design point and the curve runs to the maximum.
FLEXION_MAX_DEG = 100.0

#: Angles the matrices report, degrees.
REPORT_ANGLES_DEG = (15.0, 30.0, 45.0, 60.0, 90.0)

#: Strain at a tied end cap is a boundary artefact -- the rigid tie is a stress
#: singularity -- so peak strain is reported both everywhere and beyond this distance
#: from either cap. The latter is the number to design to.
CAP_EXCLUSION_MM = 1.0

#: Element size, mm. Two quadratic elements across the narrowest true width of the
#: 3-turn strip (0.71 mm); the 4-turn strip's 0.56 mm gets its own, smaller size.
ELEMENT_SIZE_MM = 0.35

#: Spine sagitta levels swept, mm. The exports sit at 0.75, 1.14 and 2.17.
#:
#: The lower bound is geometric. Below about 0.70 mm the spine passes inside the
#: 3.4 mm knuckle at rest -- a straight spine by 0.71 mm -- so 0.0 and 0.5 are kept
#: in the sweep only to record that verdict, and are not solved. The upper bound is
#: wearability: 3.5 mm puts the strip's top 7.4 mm above the joint axis, about
#: 2.7 mm proud of the proximal ring.
SAGITTA_LEVELS_MM = (0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)

#: Amplitude of the 4-turn pure-sine plan path, mm. The strip edge then reaches
#: +/-5.0 mm, the distal ring's own half-width, so the 4-turn part occupies the same
#: lateral envelope as the others.
FOUR_TURN_AMPLITUDE_MM = 4.0


def tpu_90a() -> HyperelasticModel:
    """Neo-Hookean TPU 90A from the Jabil datasheet modulus. See module docstring."""
    mu0 = TPU90A_MODULUS_MPA / (2.0 * (1.0 + TPU90A_POISSON))
    model = HyperelasticModel(
        kind=MaterialModelKind.NEO_HOOKEAN,
        parameters=(mu0 / 2.0,),
        name="TPU 90A (Jabil datasheet E = 19.3 MPa, Neo-Hookean)",
        poisson_ratio=TPU90A_POISSON,
        provenance=Provenance.UNVALIDATED_ASSUMPTION,
        caveats=(CAVEAT_DATASHEET_DERIVED,),
    )
    model.notes.append(
        "Initial modulus from one manufacturer's datasheet; no tensile test of the "
        "printed filament exists. Absolute torques scale with E."
    )
    return model


# -- results files --------------------------------------------------------------

def _frd_blocks(path: Path, names: tuple[str, ...]):
    """Yield (block name, step time, {node: values}) for each nodal block in a .frd.

    The .frd format is fixed width. A result block opens with a ``100C`` record
    carrying the step time, then a ``-4`` record naming the block, then ``-1``
    records of node number and values, and closes with ``-3``.
    """
    current_time = None
    name = None
    values: dict[int, list[float]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("    1PSTEP") or line[:7].strip() == "1PSTEP":
                continue
            if line.startswith("  100C"):
                try:
                    current_time = float(line[12:24])
                except ValueError:
                    current_time = None
                continue
            if line.startswith(" -4"):
                name = line.split()[1]
                values = {}
                continue
            if name is None:
                continue
            if line.startswith(" -1"):
                node = int(line[3:13])
                body = line[13:]
                numbers = [float(body[i:i + 12]) for i in range(0, len(body.rstrip("\n")), 12)
                           if body[i:i + 12].strip()]
                values[node] = numbers
            elif line.startswith(" -3"):
                if name in names:
                    yield name, current_time, values
                name = None


def _principal_engineering_strain(green: np.ndarray) -> np.ndarray:
    """Largest principal engineering strain from Green-Lagrange components.

    CalculiX writes E as (exx, eyy, ezz, exy, eyz, ezx) with tensor shear components
    under NLGEOM. The stretch along a principal direction is sqrt(1 + 2 E_i), and the
    engineering strain is that minus one.
    """
    exx, eyy, ezz, exy, eyz, ezx = (green[:, i] for i in range(6))
    tensor = np.empty((green.shape[0], 3, 3))
    tensor[:, 0, 0], tensor[:, 1, 1], tensor[:, 2, 2] = exx, eyy, ezz
    tensor[:, 0, 1] = tensor[:, 1, 0] = exy
    tensor[:, 1, 2] = tensor[:, 2, 1] = eyz
    tensor[:, 0, 2] = tensor[:, 2, 0] = ezx
    largest = np.linalg.eigvalsh(tensor)[:, -1]
    return np.sqrt(np.maximum(1.0 + 2.0 * largest, 0.0)) - 1.0


# -- one analysis ----------------------------------------------------------------

def knuckle_shell(axis_y: float, axis_z: float, radius: float):
    """The proximal link's rounded head, as a thin cylindrical sector about the axis.

    Only its outer face matters: it is the master surface the strip rides over. The
    sector spans from 60 deg below +Y, over the top, to 40 deg past +Z towards -Y --
    everything the strip can reach on its way round in 0 to 100 deg of flexion -- so
    the shell carries no more elements than it needs.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    start = math.radians(-60.0)
    frame = gp_Ax2(gp_Pnt(-KNUCKLE_HALF_LENGTH_MM, axis_y, axis_z), gp_Dir(1.0, 0.0, 0.0),
                   gp_Dir(0.0, math.cos(start), math.sin(start)))
    sweep = math.radians(190.0)
    length = 2.0 * KNUCKLE_HALF_LENGTH_MM
    outer = BRepPrimAPI_MakeCylinder(frame, radius, length, sweep).Shape()
    inner = BRepPrimAPI_MakeCylinder(frame, radius - KNUCKLE_WALL_MM, length, sweep).Shape()
    cut = BRepAlgoAPI_Cut(outer, inner)
    cut.Build()
    return cut.Shape()


def _compound(*shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def analyse_strip(shape, label: str, archive: Path, element_size: float,
                  axis_y: float, axis_z: float, flexion_deg: float,
                  timeout: float, knuckle_radius: float | None = None) -> dict:
    """Mesh, solve and post-process one strip. Returns a JSON-serialisable record."""
    knuckle_radius = KNUCKLE_RADIUS_MM if knuckle_radius is None else knuckle_radius
    solver = probe_solver(find_solver())
    material = tpu_90a()
    box = bounding_box(shape)
    axis = np.array([axis_y, axis_z])

    # Strip and knuckle are meshed separately and merged. The knuckle is fixed and
    # only its outer face matters, so it gets 1 mm elements; meshed together at the
    # strip's 0.35 mm it doubled the model to 21,700 elements for no gain.
    strip_mesh = generate_mesh(
        shape, MeshSettings(element_size=element_size, second_order=True),
        smallest_dimension=element_size * 2.0,
    )
    knuckle_mesh = generate_mesh(
        knuckle_shell(axis_y, axis_z, knuckle_radius),
        MeshSettings(element_size=KNUCKLE_ELEMENT_MM, second_order=True),
        smallest_dimension=KNUCKLE_WALL_MM,
    )
    offset = strip_mesh.node_count
    mesh = Mesh(
        nodes=np.vstack([strip_mesh.nodes, knuckle_mesh.nodes]),
        elements=np.vstack([strip_mesh.elements, knuckle_mesh.elements + offset]),
        second_order=True,
        element_size=element_size,
        node_sets={**strip_mesh.node_sets,
                   **{f"k_{name}": np.asarray(idx) + offset
                      for name, idx in knuckle_mesh.node_sets.items()}},
        quality=strip_mesh.quality,
    )
    radial0 = np.linalg.norm(mesh.nodes[:, 1:3] - axis, axis=1)
    in_knuckle = np.arange(mesh.node_count) >= offset
    strip_node = ~in_knuckle
    clearance0 = float(radial0[strip_node].min() - knuckle_radius)
    if clearance0 < 0.0:
        # Checked before solving: a strip that starts inside the finger would be
        # pushed out by the contact penalty and the "restoring torque" would include
        # that preload. It is a geometric verdict, not an analysis.
        return {"label": label, "failure": (
            f"strip starts {-clearance0:.3f} mm inside the {knuckle_radius} mm "
            "knuckle: the spine is too flat to clear the joint at rest"),
            "geometric_interference_mm": -clearance0, "reached_deg": 0.0}

    def sets_where(predicate):
        return sorted(name for name, idx in mesh.node_sets.items()
                      if predicate(np.asarray(idx)))

    knuckle_sets = sets_where(lambda idx: in_knuckle[idx].all())
    knuckle_outer = sets_where(
        lambda idx: in_knuckle[idx].all()
        and np.allclose(radial0[idx], knuckle_radius, atol=1e-2))
    # End caps only. The strip's long faces run its whole length, so "every node
    # within the depth" selects exactly the caps; 0.12 mm covers the distal cap of
    # the exports, which is cut 0.08 mm out of square.
    proximal = sets_where(lambda idx: strip_node[idx].all()
                          and mesh.nodes[idx, 1].max() <= box.ymin + 0.12)
    distal = sets_where(lambda idx: strip_node[idx].all()
                        and mesh.nodes[idx, 1].min() >= box.ymax - 0.12)
    strip_skin = sets_where(lambda idx: strip_node[idx].all())
    strip_skin = [n for n in strip_skin if n not in proximal and n not in distal]
    if not proximal or not distal or not knuckle_outer or not strip_skin:
        raise RuntimeError(f"{label}: set classification failed "
                           f"({proximal}, {distal}, {knuckle_outer}, {len(strip_skin)}).")

    distal_nodes = np.unique(np.concatenate([mesh.node_sets[s] for s in distal]))
    cap_x = float(mesh.nodes[distal_nodes, 0].mean())
    rigid = RigidBody(node_sets=distal, reference_point=(cap_x, axis_y, axis_z),
                      name="distal", pin_reference=True)
    contact = ContactPair(
        name="knuckle",
        slave=ContactSurface.from_node_sets(mesh, strip_skin, "strip_skin", SurfaceType.NODE),
        master=ContactSurface.from_node_sets(mesh, knuckle_outer, "knuckle_face",
                                             SurfaceType.ELEMENT),
        stiffness=ContactPair.suggested_stiffness(TPU90A_MODULUS_MPA, element_size),
    )
    settings = DeckSettings(
        nlgeom=True,
        increments=60,
        initial_increment=0.01,
        minimum_increment=1.0e-6,
        maximum_increment=0.02,
        rigid_bodies=[rigid],
        reaction_sets=[rigid.rotation_set_name],
        field_output_frequency=1,
        contact_pairs=[contact],
    )
    boundary = [BoundaryCondition(n, (1, 2, 3), 0.0, "proximal ring face held")
                for n in proximal]
    boundary += [BoundaryCondition(n, (1, 2, 3), 0.0, "knuckle is part of the proximal link")
                 for n in knuckle_sets]
    boundary.append(BoundaryCondition(
        rigid.rotation_set_name, (1,), -math.radians(flexion_deg),
        f"PIP flexion {flexion_deg:g} deg about +X, distal ring towards -Z",
    ))
    # The joint is a hinge: the distal ring cannot rotate about Y or Z. Leaving these
    # two rotations free is not merely less faithful, it does not solve -- the first
    # attempt cut the increment back to 0.01 deg, with the largest residual on the
    # rotation node's Z rotation, and converged in one increment once they were held.
    boundary.append(BoundaryCondition(
        rigid.rotation_set_name, (2, 3), 0.0,
        "hinge: distal ring does not rotate about Y or Z",
    ))
    deck = write_deck(mesh, material, boundary, settings, title=f"A8 meander {label}")
    # Displacements and strains only; stress is not post-processed and doubles the
    # file. INC raised so a run with many cutbacks is not stopped by the cap.
    deck = deck.replace("U, RF", "U").replace("S, E", "E")
    deck = re.sub(r"(\*STEP, NLGEOM), INC=\d+", r"\1, INC=2000", deck)
    # Let the increment grow after increments that take up to eight iterations, not
    # CalculiX's default four. Without contact this model settles at five per
    # increment and with contact at seven, so with the default the step never grew:
    # 0.25 deg for all 400 increments, about 100 minutes a run. Convergence
    # tolerances are untouched; only the step-size policy changes.
    deck = deck.replace(
        "*STATIC\n",
        "*CONTROLS, PARAMETERS=TIME INCREMENTATION\n8, 12, 9, 20, 10, 8\n*STATIC\n", 1,
    )

    started = time.perf_counter()
    result = run_analysis(deck, mesh, material, solver, archive_directory=archive,
                          timeout=timeout)
    wall = time.perf_counter() - started
    run_dir = result.run_directory

    history = parse_dat_reaction_history(run_dir / "results.dat").get(
        rigid.rotation_set_name.upper(), []
    )
    times = np.array([t for t, _ in history])
    # The reaction on the driven rotation node is the moment that had to be applied
    # to impose the flexion, so it has the sign of the (negative) rotation. The
    # strip's restoring torque on the finger is its opposite, reported positive.
    torque = np.array([-v[0] for _, v in history])
    angle = times * flexion_deg

    # Field post-processing, one increment at a time.
    y0 = mesh.nodes[:, 1]
    interior = ((y0 > box.ymin + CAP_EXCLUSION_MM) & (y0 < box.ymax - CAP_EXCLUSION_MM)
                & strip_node)
    corner = np.unique(mesh.elements[:, :4])
    axis = np.array([axis_y, axis_z])
    fields: dict[float, dict] = {}
    frd = run_dir / "results.frd"
    if frd.is_file():
        for name, t, values in _frd_blocks(frd, ("DISP", "TOSTRAIN", "STRAIN")):
            if t is None:
                continue
            entry = fields.setdefault(round(t, 6), {})
            nodes = np.array([n for n in sorted(values) if n <= mesh.node_count]) - 1
            data = np.array([values[n + 1] for n in nodes])
            if name == "DISP":
                keep = strip_node[nodes]
                deformed = (mesh.nodes[nodes] + data[:, :3])[keep]
                radial = np.linalg.norm(deformed[:, 1:3] - axis, axis=1)
                entry["min_radius_mm"] = float(radial.min())
                entry["lateral_extent_mm"] = float(deformed[:, 0].max() - deformed[:, 0].min())
            else:
                strain = _principal_engineering_strain(data[:, :6])
                mask_corner = np.isin(nodes, corner) & strip_node[nodes]
                entry["peak_strain_all"] = float(strain[mask_corner].max())
                entry["peak_strain_interior"] = float(
                    strain[mask_corner & interior[nodes]].max()
                )
        frd.unlink()  # hundreds of MB per run; the scalars above are what is kept

    field_times = np.array(sorted(fields))

    def field_at(key: str, target_deg: float):
        if field_times.size == 0:
            return None
        target = target_deg / flexion_deg
        if target > field_times.max() + 1e-6:
            return None
        usable = [t for t in field_times if key in fields[t]]
        if not usable:
            return None
        nearest = min(usable, key=lambda t: abs(t - target))
        return fields[nearest][key]

    reached = float(angle.max()) if angle.size else 0.0

    def torque_at(deg: float):
        if angle.size == 0 or deg > reached + 1e-6:
            return None
        return float(np.interp(deg, np.concatenate([[0.0], angle]),
                               np.concatenate([[0.0], torque])))

    # Initial stiffness: secant through the first increments up to 3 degrees.
    small = angle <= 3.0 + 1e-9
    k0 = (float(np.polyfit(np.radians(angle[small]), torque[small], 1)[0])
          if small.sum() >= 2 else
          (float(torque[0] / math.radians(angle[0])) if angle.size else None))

    # Energy stored 0 to 90 degrees, N.mm (= mJ).
    energy = None
    if reached >= 90.0 - 1e-6:
        grid = np.linspace(0.0, 90.0, 181)
        tq = np.interp(grid, np.concatenate([[0.0], angle]), np.concatenate([[0.0], torque]))
        energy = float(np.trapezoid(tq, np.radians(grid)))

    # Monotonicity: a falling torque with rising flexion is buckling or snap-through,
    # which a spring-back element must not do.
    drops = np.diff(torque) < -0.02 * max(1e-9, float(np.abs(torque).max()))
    first_drop = float(angle[1:][drops][0]) if drops.any() else None

    record = {
        "label": label,
        "converged": bool(result.convergence.converged),
        "reached_deg": reached,
        "increments": int(result.convergence.increments_completed),
        "cutbacks": int(result.convergence.cutbacks),
        "wall_seconds": round(wall, 1),
        "mesh": {"elements": mesh.element_count, "nodes": mesh.node_count,
                 "element_size_mm": element_size},
        "knuckle_radius_mm": knuckle_radius,
        "clearance_at_rest_mm": clearance0,
        "axis_point_mm": [cap_x, axis_y, axis_z],
        "material": material.describe(),
        "k0_n_mm_per_rad": k0,
        "torque_n_mm": {f"{a:g}": torque_at(a) for a in REPORT_ANGLES_DEG},
        "torque_max_n_mm": torque_at(min(reached, flexion_deg)),
        "energy_0_90_n_mm": energy,
        "linearity_t90_over_k0": (
            torque_at(90.0) / (k0 * math.radians(90.0))
            if torque_at(90.0) is not None and k0 else None
        ),
        "first_torque_drop_deg": first_drop,
        "peak_strain_interior": {f"{a:g}": field_at("peak_strain_interior", a)
                                 for a in REPORT_ANGLES_DEG},
        "peak_strain_all": {f"{a:g}": field_at("peak_strain_all", a)
                            for a in REPORT_ANGLES_DEG},
        "min_radius_from_axis_mm": {f"{a:g}": field_at("min_radius_mm", a)
                                    for a in (0.0,) + REPORT_ANGLES_DEG},
        "lateral_extent_mm": {f"{a:g}": field_at("lateral_extent_mm", a)
                              for a in (0.0,) + REPORT_ANGLES_DEG},
        "curve": {"angle_deg": angle.tolist(), "torque_n_mm": torque.tolist()},
        "field_history": {f"{t:.6f}": v for t, v in fields.items()},
        "convergence_summary": result.convergence.summary,
        "run_directory": str(run_dir),
    }
    # The fixed sign convention above is checked, not assumed: a spring that pushes
    # the finger further into flexion would be reported as a negative torque.
    if angle.size and torque[0] < 0:
        record["sign_warning"] = "Reaction moment assists flexion at the first increment."
    return record


# -- the study ---------------------------------------------------------------------

def _variant(n_turns: int, sagitta: float, label: str) -> A8MeanderParameters:
    if n_turns == 2:
        plan, per_lobe = A8_PLAN_2TURN, 24
    elif n_turns == 3:
        plan, per_lobe = A8_PLAN_3TURN, 24
    else:
        plan, per_lobe = sine_plan(n_turns, FOUR_TURN_AMPLITUDE_MM), 24
    return A8MeanderParameters(plan=plan, sagitta=sagitta, n_turns=n_turns,
                               stations_per_lobe=per_lobe, label=label)


def plan_runs(steps_dir: Path | None, groups: list[str]) -> list[dict]:
    runs: list[dict] = []
    if "exports" in groups and steps_dir is not None:
        for stem, n_turns in (("A8_PIP_Meander_2turn_2mm", 2),
                              ("A8_PIP_Meander_3turn_2mm", 3),
                              ("A8_PIP_Meander_3turn_2mm_2", 3)):
            runs.append({"label": f"export_{stem}", "kind": "export",
                         "step": steps_dir / f"{stem}.STEP", "n_turns": n_turns,
                         "sagitta": A8_MEASURED_SAGITTA[stem]})
    if "replicas" in groups:
        for stem, n_turns in (("A8_PIP_Meander_2turn_2mm", 2),
                              ("A8_PIP_Meander_3turn_2mm", 3),
                              ("A8_PIP_Meander_3turn_2mm_2", 3)):
            runs.append({"label": f"replica_{stem}", "kind": "replica",
                         "n_turns": n_turns, "sagitta": A8_MEASURED_SAGITTA[stem]})
    if "sweep" in groups:
        for n_turns in (2, 3, 4):
            for sagitta in SAGITTA_LEVELS_MM:
                runs.append({"label": f"sweep_{n_turns}T_s{sagitta:.2f}", "kind": "sweep",
                             "n_turns": n_turns, "sagitta": sagitta})
    return runs


def strip_from_export(step: Path):
    """The strip body of an export: the largest solid that is not a ring.

    The exports hold the two rings, the strip, and (in the 3-turn files) a
    0.021 mm^3 sliver at the proximal joint. The rings are the bodies whose Y extent
    is 3 mm; the strip is the one that spans between them.
    """
    model = load_geometry(step)
    spanning = [s for s in model.solids
                if s.bounding_box.ymax - s.bounding_box.ymin > 20.0]
    if len(spanning) != 1:
        raise RuntimeError(f"{step.name}: expected one spanning strip, found {len(spanning)}.")
    return spanning[0].shape


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--steps-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--groups", default="exports,replicas,sweep")
    parser.add_argument("--only", default=None, help="Comma-separated labels to run.")
    parser.add_argument("--axis-y", type=float, default=AXIS_Y_MM)
    parser.add_argument("--axis-z", type=float, default=AXIS_Z_MM)
    parser.add_argument("--axis-variants", default=None,
                        help="Rerun one label at shifted axes: LABEL:dy1/dz1,dy2/dz2,...")
    parser.add_argument("--flexion", type=float, default=FLEXION_MAX_DEG)
    parser.add_argument("--element-size", type=float, default=ELEMENT_SIZE_MM)
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--archive", type=Path, default=None)
    args = parser.parse_args(argv)

    runs_dir = args.out / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    archive = args.archive or Path("/tmp") / "a8_runs"

    runs = plan_runs(args.steps_dir, args.groups.split(","))
    if args.axis_variants:
        base, offsets = args.axis_variants.split(":")
        template = next(r for r in plan_runs(args.steps_dir, ["exports", "replicas", "sweep"])
                        if r["label"] == base)
        runs = []
        for pair in offsets.split(","):
            dy, dz = (float(v) for v in pair.split("/"))
            runs.append(dict(template, label=f"axis_{base}_dy{dy:+g}_dz{dz:+g}",
                             axis_y=args.axis_y + dy, axis_z=args.axis_z + dz,
                             kind="axis_sensitivity", base=base))
    if args.only:
        wanted = set(args.only.split(","))
        runs = [r for r in runs if r["label"] in wanted]

    for run in runs:
        target = runs_dir / f"{run['label']}.json"
        if target.exists():
            print(f"skip  {run['label']} (done)")
            continue
        if run["kind"] == "export":
            shape = strip_from_export(run["step"])
            geometry = None
        else:
            params = _variant(run["n_turns"], run["sagitta"], run["label"])
            shape = build_a8_meander(params)
            geometry = params.path_metrics()
        size = args.element_size
        if geometry and geometry["min_true_width_mm"] < 2.0 * size:
            size = round(geometry["min_true_width_mm"] / 2.0, 3)
        print(f"run   {run['label']}  (element size {size} mm)", flush=True)
        try:
            record = analyse_strip(
                shape, run["label"], archive, size,
                run.get("axis_y", args.axis_y), run.get("axis_z", args.axis_z),
                args.flexion, args.timeout,
            )
        except Exception as exc:  # recorded, not swallowed: a failure is a result
            record = {"label": run["label"], "failure": f"{type(exc).__name__}: {exc}"}
        record.update({k: (str(v) if isinstance(v, Path) else v) for k, v in run.items()})
        if geometry:
            record["geometry"] = geometry
        target.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"done  {run['label']}: reached {record.get('reached_deg')} deg, "
              f"T90 {record.get('torque_n_mm', {}).get('90')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
