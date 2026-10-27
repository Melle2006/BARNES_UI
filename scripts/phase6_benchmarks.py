"""Phase 6 benchmarks: establish what the solver can actually do here.

Phase 6 is explicitly investigative with a permitted negative outcome. "We tried
self-contact, it would not converge, here is the evidence" is a successful result.

This script runs one benchmark per capability, each against an answer known in
advance, and writes the verdict to ``results/phase6/capabilities.json``. The
application reads that file and offers only the capabilities that passed -- criterion
2 -- so running this script is what turns a feature on, and running it on a different
machine or a different CalculiX build is what tells you whether the feature is on
there too.

    python scripts/phase6_benchmarks.py                 # everything
    python scripts/phase6_benchmarks.py --only gravity contact_friction

Each benchmark's geometry is a box or a pair of boxes, deliberately: the point is to
test the solver feature, and a shape whose exact answer comes from a textbook formula
is the only kind that can do that. Real geometry comes afterwards, once the feature is
known to work at all.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.cad._occ import occ, require_kernel  # noqa: E402
from barnes_ui.core.fea.capabilities import (  # noqa: E402
    Capability,
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStatus,
)
from barnes_ui.core.fea.contact import (  # noqa: E402
    ContactFormulation,
    ContactPair,
    ContactSurface,
    SurfaceType,
)
from barnes_ui.core.fea.deck import (  # noqa: E402
    BoundaryCondition,
    DeckSettings,
    write_deck,
)
from barnes_ui.core.fea.loads import (  # noqa: E402
    STANDARD_GRAVITY_MM_S2,
    GravityLoad,
    PointLoad,
    density_from_g_per_cm3,
)
from barnes_ui.core.fea.meshing import Mesh, MeshSettings, generate_mesh  # noqa: E402
from barnes_ui.core.fea.runner import run_analysis  # noqa: E402
from barnes_ui.core.fea.solver import find_solver, probe_solver  # noqa: E402
from barnes_ui.core.material.models import (  # noqa: E402
    HyperelasticModel,
    MaterialModelKind,
)
from barnes_ui.core.provenance import Provenance  # noqa: E402

#: Benchmark material. Linear elastic on purpose: every closed form below assumes it,
#: and a hyperelastic material would mean comparing against a formula that does not
#: describe the model. The capability under test is the solver feature, not the
#: constitutive law -- that was Phase 3 criterion 2.
E_MPA = 1000.0
NU = 0.3
#: TPU-ish, from a filament datasheet rather than invented: 1.2 g/cm^3.
DENSITY_G_PER_CM3 = 1.2

TOL = 1.0e-6


def benchmark_material() -> HyperelasticModel:
    return HyperelasticModel(
        kind=MaterialModelKind.LINEAR_ELASTIC,
        parameters=(E_MPA, NU),
        name="benchmark-elastic",
        poisson_ratio=NU,
        provenance=Provenance.ANALYTICAL_ESTIMATE,
        caveats=(),
        notes=["Synthetic benchmark material; not a TPU property."],
    )


# --------------------------------------------------------------- geometry


def box(dx: float, dy: float, dz: float, at=(0.0, 0.0, 0.0)):
    require_kernel()
    return occ.BRepPrimAPI_MakeBox(occ.gp_Pnt(*at), dx, dy, dz).Shape()


def compound(*shapes):
    require_kernel()
    result = occ.TopoDS_Compound()
    builder = occ.BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def surfaces_where(mesh: Mesh, predicate: Callable[[np.ndarray], bool]) -> list[str]:
    """Surface sets every one of whose nodes satisfies ``predicate``.

    "Every node" rather than "any node": a set that straddles the selection is not a
    partial match, it is a different surface, and including it would silently extend
    a boundary condition onto geometry nobody chose.
    """
    chosen = []
    for name, indices in mesh.node_sets.items():
        points = mesh.nodes[np.asarray(indices)]
        if all(predicate(p) for p in points):
            chosen.append(name)
    return sorted(chosen)


def node_displacements(result, mesh: Mesh) -> np.ndarray | None:
    """Displacements aligned with the mesh's node indexing, or None."""
    if result.displacements is None:
        return None
    values = np.asarray(result.displacements)
    if values.shape[0] < mesh.node_count:
        return None
    return values[: mesh.node_count]


# --------------------------------------------------------------- plumbing


@dataclass
class BenchmarkOutcome:
    """What one benchmark found."""

    capability: Capability
    passed: bool
    evidence: str
    measured: float | None = None
    expected: float | None = None
    tolerance: float | None = None
    convergence: str = ""
    run_directory: str | None = None

    def to_record(self, solver_version: str) -> CapabilityRecord:
        return CapabilityRecord(
            capability=self.capability,
            status=(
                CapabilityStatus.PASSED if self.passed else CapabilityStatus.FAILED
            ),
            evidence=self.evidence,
            measured=self.measured,
            expected=self.expected,
            tolerance=self.tolerance,
            convergence=self.convergence,
            run_directory=self.run_directory,
            solver_version=solver_version,
        )


def submit(mesh, boundary, settings, title, solver, archive):
    material = benchmark_material()
    deck = write_deck(mesh, material, boundary, settings, title=title)
    return run_analysis(
        deck, mesh, material, solver, archive_directory=archive, timeout=3600.0
    )


# -------------------------------------------------------------- benchmarks


#: Cantilever used by the gravity and tendon benchmarks.
CANTILEVER = (60.0, 8.0, 4.0)


def _cantilever_mesh() -> Mesh:
    return generate_mesh(
        box(*CANTILEVER), MeshSettings(elements_through_thickness=3)
    )


def _root_sets(mesh: Mesh) -> list[str]:
    return surfaces_where(mesh, lambda p: p[0] < TOL)


def benchmark_gravity(solver, archive) -> BenchmarkOutcome:
    """A cantilever sagging under its own weight.

    Closed form for a uniformly loaded cantilever, with the shear term that a short
    beam needs:

        delta = q L^4 / (8 E I) + q L^2 / (2 G A_s),   A_s = (5/6) A

    This is the cheapest possible test of three things at once: the ``*DENSITY``
    path, the ``*DLOAD, GRAV`` path, and the tonne-per-cubic-millimetre unit system.
    A density entered in g/cm^3 would overstate the deflection by a factor of 1e9 and
    the run would converge perfectly.
    """
    length, width, height = CANTILEVER
    mesh = _cantilever_mesh()
    density = density_from_g_per_cm3(DENSITY_G_PER_CM3)

    area = width * height
    inertia = width * height ** 3 / 12.0
    shear_modulus = E_MPA / (2.0 * (1.0 + NU))
    q = density * area * STANDARD_GRAVITY_MM_S2         # N/mm
    expected = (
        q * length ** 4 / (8.0 * E_MPA * inertia)
        + q * length ** 2 / (2.0 * shear_modulus * (5.0 / 6.0) * area)
    )

    root = _root_sets(mesh)
    settings = DeckSettings(
        nlgeom=False,
        reaction_sets=root,
        field_output_frequency=1,
        gravity=GravityLoad(density=density, direction=(0.0, 0.0, -1.0)),
    )
    boundary = [BoundaryCondition(name, (1, 2, 3), 0.0, "root fixed") for name in root]
    result = submit(mesh, boundary, settings, "Phase 6: self-weight cantilever",
                    solver, archive)

    if not result.is_trustworthy:
        return BenchmarkOutcome(
            Capability.GRAVITY, False,
            "The self-weight run did not produce a trustworthy solution.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )

    displacements = node_displacements(result, mesh)
    if displacements is None:
        return BenchmarkOutcome(
            Capability.GRAVITY, False,
            "No displacement field was written, so the tip deflection could not be "
            "read. Field output must be enabled for this benchmark.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )

    tip = np.abs(displacements[mesh.nodes[:, 0] > length - TOL, 2]).max()
    tolerance = 0.05
    error = (tip - expected) / expected
    return BenchmarkOutcome(
        Capability.GRAVITY,
        abs(error) <= tolerance,
        (
            f"Cantilever {length}x{width}x{height} mm at {DENSITY_G_PER_CM3} g/cm^3 "
            f"under {STANDARD_GRAVITY_MM_S2:.1f} mm/s^2. Distributed load "
            f"{q:.6g} N/mm. Tip deflection {tip:.6g} mm against the closed-form "
            f"{expected:.6g} mm (bending plus shear), {error * 100:+.2f} %. "
            f"{mesh.describe()}."
        ),
        measured=float(tip), expected=float(expected), tolerance=tolerance,
        convergence=result.convergence.summary,
        run_directory=str(result.run_directory),
    )


def benchmark_tendon(solver, archive) -> BenchmarkOutcome:
    """A concentrated load on a node set, checked by global equilibrium.

    A tendon is modelled as a force on an attachment patch. The thing that goes wrong
    is not the physics but the bookkeeping: ``*CLOAD`` on a set applies the stated
    force to *every* node in it, so a 2 N tendon on a 300-node patch becomes 600 N.
    PointLoad(total=True) divides it; this benchmark is what proves it divides it
    correctly.
    """
    length = CANTILEVER[0]
    mesh = _cantilever_mesh()
    tip = surfaces_where(mesh, lambda p: p[0] > length - TOL)
    root = _root_sets(mesh)
    applied = 2.0

    settings = DeckSettings(
        nlgeom=False,
        reaction_sets=root,
        point_loads=[
            PointLoad(node_set=tip[0], force=(0.0, 0.0, -applied), total=True,
                      description="tendon pull at the tip")
        ],
    )
    boundary = [BoundaryCondition(name, (1, 2, 3), 0.0, "root fixed") for name in root]
    result = submit(mesh, boundary, settings, "Phase 6: tendon point load",
                    solver, archive)

    if not result.is_trustworthy:
        return BenchmarkOutcome(
            Capability.TENDON_LOAD, False,
            "The tendon-load run did not produce a trustworthy solution.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )

    total = np.zeros(3)
    for name in root:
        if result.has_reaction(name):
            total += result.reaction(name)
    measured = float(total[2])
    tolerance = 0.005
    error = (measured - applied) / applied
    return BenchmarkOutcome(
        Capability.TENDON_LOAD,
        abs(error) <= tolerance,
        (
            f"{applied} N applied as a resultant over the tip patch "
            f"({len(mesh.node_sets[tip[0]])} nodes); root reaction "
            f"{measured:.6g} N, {error * 100:+.3f} %. A per-node interpretation "
            f"would have given {applied * len(mesh.node_sets[tip[0]]):.0f} N."
        ),
        measured=measured, expected=applied, tolerance=tolerance,
        convergence=result.convergence.summary,
        run_directory=str(result.run_directory),
    )


#: Two stacked blocks for the contact benchmarks: 20 x 20 x 10 each.
STACK = (20.0, 20.0, 10.0)


def _stack_mesh() -> Mesh:
    lower = box(*STACK)
    upper = box(*STACK, at=(0.0, 0.0, STACK[2]))
    return generate_mesh(
        compound(lower, upper),
        MeshSettings(element_size=4.0, second_order=True),
        smallest_dimension=STACK[2],
    )


def surface_body_side(mesh: Mesh, name: str, plane_z: float) -> str:
    """Which side of ``plane_z`` the elements behind a surface set lie on.

    Two stacked blocks have coincident faces at the interface, so a coordinate test
    cannot tell them apart -- both sets have every node at z = 10. What distinguishes
    them is the material behind the face. This looks at the elements that own the
    surface's nodes and reports "lower" or "upper" from their centroids.

    Without this, a contact pair would list each block's interface face as both
    slave and master, so every node would be in contact with the face it belongs to.
    """
    nodes = set(int(i) for i in np.asarray(mesh.node_sets[name]).ravel())
    corners = mesh.elements[:, :4]
    owning = np.array([
        any(int(n) in nodes for n in element) for element in corners
    ])
    if not owning.any():  # pragma: no cover - a surface always has elements
        return "unknown"
    centroids = mesh.nodes[corners[owning]].mean(axis=1)
    return "lower" if centroids[:, 2].mean() < plane_z else "upper"


def _stack_surfaces(mesh: Mesh):
    height = STACK[2]
    base = surfaces_where(mesh, lambda p: p[2] < TOL)
    top = surfaces_where(mesh, lambda p: p[2] > 2 * height - TOL)
    interface = surfaces_where(mesh, lambda p: abs(p[2] - height) < TOL)
    lower = [n for n in interface if surface_body_side(mesh, n, height) == "lower"]
    upper = [n for n in interface if surface_body_side(mesh, n, height) == "upper"]
    return base, lower, upper, top


def _contact_pair(mesh: Mesh, slave_sets: Sequence[str], master_sets: Sequence[str],
                  friction: float, name: str) -> ContactPair:
    stiffness = ContactPair.suggested_stiffness(E_MPA, mesh.element_size)
    return ContactPair(
        name=name,
        slave=ContactSurface.from_node_sets(
            mesh, slave_sets, f"{name}_slave", SurfaceType.NODE
        ),
        master=ContactSurface.from_node_sets(
            mesh, master_sets, f"{name}_master", SurfaceType.ELEMENT
        ),
        formulation=ContactFormulation.NODE_TO_SURFACE,
        stiffness=stiffness,
        friction=friction,
    )


#: Contact configurations to try, in order, until one converges.
#:
#: Phase 6's question is whether contact works here at all, so trying one formulation
#: and reporting "contact does not converge" would conflate the feature with one set
#: of settings. Every attempt is recorded and the evidence names the one that worked,
#: which is then the setting the application should use.
CONTACT_ATTEMPTS = (
    ("node-to-surface, K = 10E/h", ContactFormulation.NODE_TO_SURFACE, 10.0),
    ("node-to-surface, K = E/h", ContactFormulation.NODE_TO_SURFACE, 1.0),
    ("surface-to-surface, K = 10E/h", ContactFormulation.SURFACE_TO_SURFACE, 10.0),
    ("surface-to-surface, K = E/h", ContactFormulation.SURFACE_TO_SURFACE, 1.0),
)


def benchmark_contact(solver, archive, friction: float) -> BenchmarkOutcome:
    """Two blocks in contact, loaded through the interface.

    Frictionless case: 100 N pressed down through the joint must appear in full at
    the fixed base. The upper block's in-plane motion is restrained, because a
    frictionless interface provides no tangential stiffness and the model would
    otherwise carry two rigid-body modes.

    Friction case: the same normal load plus a tangential load of 10 N, with mu=0.3.
    Both ramp together, so the Coulomb limit 0.3 * 100t always exceeds the applied
    10t and the blocks must stick for the whole step. Nothing restrains the upper
    block in plane except friction, so a divergence here is a real negative result
    rather than a failed check that equilibrium holds.
    """
    capability = (
        Capability.CONTACT_FRICTION if friction > 0.0
        else Capability.CONTACT_FRICTIONLESS
    )
    mesh = _stack_mesh()
    base, lower_face, upper_face, top = _stack_surfaces(mesh)
    if not base or not lower_face or not upper_face or not top:
        return BenchmarkOutcome(
            capability, False,
            f"Surface classification failed: {len(base)} base, "
            f"{len(lower_face)} lower-interface, {len(upper_face)} upper-interface, "
            f"{len(top)} top sets.",
        )

    normal = 100.0
    tangential = 10.0 if friction > 0.0 else 0.0
    attempted: list[str] = []
    result = None
    label = ""
    pair = None

    for label, formulation, factor in CONTACT_ATTEMPTS:
        slave_kind = (
            SurfaceType.ELEMENT
            if formulation is ContactFormulation.SURFACE_TO_SURFACE
            else SurfaceType.NODE
        )
        # The upper block's face is the slave, the lower block's the master. The
        # softer or finer body is conventionally the slave; here the two are
        # identical, so the choice is arbitrary and is recorded rather than implied.
        pair = ContactPair(
            name="stack",
            slave=ContactSurface.from_node_sets(
                mesh, upper_face, "stack_slave", slave_kind
            ),
            master=ContactSurface.from_node_sets(
                mesh, lower_face, "stack_master", SurfaceType.ELEMENT
            ),
            formulation=formulation,
            stiffness=factor * E_MPA / mesh.element_size,
            friction=friction,
        )

        settings = DeckSettings(
            nlgeom=True,
            increments=40,
            initial_increment=0.02,
            # Contact chatters as nodes change state, and chatter is resolved by
            # letting the solver cut back much further than a smooth nonlinear
            # problem ever needs to.
            minimum_increment=1.0e-8,
            maximum_increment=0.1,
            reaction_sets=base,
            field_output_frequency=1,
            contact_pairs=[pair],
            point_loads=[
                PointLoad(
                    node_set=top[0], force=(tangential, 0.0, -normal), total=True,
                    description="normal and tangential load on the upper block",
                )
            ],
        )
        boundary = [
            BoundaryCondition(name, (1, 2, 3), 0.0, "base fixed") for name in base
        ]
        if friction <= 0.0:
            boundary.extend(
                BoundaryCondition(
                    name, (1, 2), 0.0,
                    "upper block held in plane; a frictionless interface offers no "
                    "tangential stiffness",
                )
                for name in top
            )

        result = submit(
            mesh, boundary, settings,
            f"Phase 6: stacked-block contact, mu={friction}, {label}",
            solver, archive,
        )
        attempted.append(f"{label}: {result.convergence.summary}")
        if result.is_trustworthy:
            break
    else:
        return BenchmarkOutcome(
            capability, False,
            "No contact configuration converged on two stacked blocks. Attempts: "
            + "; ".join(attempted)
            + ". For the friction case a divergence is meaningful in itself, since "
            "nothing but friction holds the upper block in place.",
            convergence=attempted[-1] if attempted else "",
            run_directory=str(result.run_directory) if result else None,
        )

    total = np.zeros(3)
    for name in base:
        if result.has_reaction(name):
            total += result.reaction(name)

    tried = f"Converged with {label}. Attempts: " + "; ".join(attempted) + ". "

    if friction > 0.0:
        measured, expected, tolerance = float(total[0]), -tangential, 0.02
        # Sign convention: the reaction opposes the applied load.
        error = (abs(measured) - abs(expected)) / abs(expected)
        slid = _maximum_interface_slip(result, mesh)
        passed = abs(error) <= tolerance and slid < 0.05
        evidence = tried + (
            f"Normal {normal} N and tangential {tangential} N with mu={friction}, so "
            f"the Coulomb limit {friction * normal:.0f} N is never reached. Base "
            f"tangential reaction {measured:.6g} N against {expected:.6g} N "
            f"({error * 100:+.3f} %). Peak in-plane displacement of the upper block "
            f"{slid:.4g} mm; anything approaching an element size would be sliding."
        )
    else:
        measured, expected, tolerance = float(total[2]), normal, 0.02
        error = (abs(measured) - expected) / expected
        penetration = _interface_penetration(result, mesh)
        passed = abs(error) <= tolerance and penetration < 0.05 * mesh.element_size
        evidence = tried + (
            f"{normal} N pressed through the interface; base reaction "
            f"{measured:.6g} N, {error * 100:+.3f} %. Interface penetration "
            f"{penetration:.4g} mm against an element size of "
            f"{mesh.element_size:.3g} mm. Penalty stiffness {pair.stiffness:.4g} "
            f"N/mm^3. {mesh.describe()}."
        )

    return BenchmarkOutcome(
        capability, passed, evidence,
        measured=measured, expected=float(expected), tolerance=tolerance,
        convergence=result.convergence.summary,
        run_directory=str(result.run_directory),
    )


def _interface_penetration(result, mesh: Mesh) -> float:
    """How far the two blocks overlapped at the interface, in mm.

    Measured as the drop in the gap between the two coincident node layers at
    z = 10 mm. A penalty formulation always lets some penetration happen; the
    question is whether it is a small fraction of an element or a visible fraction
    of the part.
    """
    displacements = node_displacements(result, mesh)
    if displacements is None:
        return float("nan")
    at_interface = np.abs(mesh.nodes[:, 2] - STACK[2]) < TOL
    if not at_interface.any():
        return float("nan")
    deflections = displacements[at_interface, 2]
    return float(deflections.max() - deflections.min())


def _maximum_interface_slip(result, mesh: Mesh) -> float:
    """Largest in-plane displacement anywhere in the upper block, in mm."""
    displacements = node_displacements(result, mesh)
    if displacements is None:
        return float("nan")
    upper = mesh.nodes[:, 2] > STACK[2] + TOL
    if not upper.any():
        return float("nan")
    return float(np.linalg.norm(displacements[upper, :2], axis=1).max())


#: Mechanical-stop benchmark: a cantilever deflected onto a rigid shelf below it.
STOP_GAP = 0.5


def benchmark_mechanical_stop(solver, archive) -> BenchmarkOutcome:
    """A beam loaded down onto a stop placed a known gap below it.

    The expected answer needs no FEA: once the beam is on the stop, its tip
    deflection is the gap. Loading it to three times the force that would just close
    the gap means a stop that is not working gives roughly three times the gap, and
    one that is working gives the gap -- a factor of three apart, which no tolerance
    argument can blur.
    """
    length, width, height = CANTILEVER
    inertia = width * height ** 3 / 12.0
    stiffness = 3.0 * E_MPA * inertia / length ** 3
    contact_force = stiffness * STOP_GAP
    applied = 3.0 * contact_force

    beam = box(length, width, height)
    # A shelf under the last 10 mm of the beam, separated by the gap.
    shelf = box(10.0, width, 4.0, at=(length - 10.0, 0.0, -STOP_GAP - 4.0))
    mesh = generate_mesh(
        compound(beam, shelf),
        MeshSettings(element_size=1.6, second_order=True),
        smallest_dimension=height,
    )

    root = surfaces_where(mesh, lambda p: p[0] < TOL and p[2] > -TOL)
    shelf_base = surfaces_where(mesh, lambda p: p[2] < -STOP_GAP - 4.0 + TOL)
    # The beam's underside is a single face running the whole length, so it cannot
    # be selected by restricting x to the part above the shelf: no surface set has
    # *every* node there. Taking the whole underside as the slave is correct anyway
    # -- the master is the shelf, and contact only happens where the two meet.
    beam_underside = surfaces_where(mesh, lambda p: abs(p[2]) < TOL)
    shelf_top = surfaces_where(mesh, lambda p: abs(p[2] + STOP_GAP) < TOL)
    tip = surfaces_where(mesh, lambda p: p[0] > length - TOL and p[2] > -TOL)

    missing = [
        label for label, sets in (
            ("root", root), ("shelf base", shelf_base),
            ("beam underside", beam_underside), ("shelf top", shelf_top),
            ("tip", tip),
        ) if not sets
    ]
    if missing:
        return BenchmarkOutcome(
            Capability.MECHANICAL_STOPS, False,
            f"Surface classification found no {', '.join(missing)} set(s), so the "
            "benchmark could not be set up.",
        )

    pair = ContactPair(
        name="stop",
        slave=ContactSurface.from_node_sets(
            mesh, beam_underside, "stop_slave", SurfaceType.NODE
        ),
        master=ContactSurface.from_node_sets(
            mesh, shelf_top, "stop_master", SurfaceType.ELEMENT
        ),
        stiffness=ContactPair.suggested_stiffness(E_MPA, mesh.element_size),
    )
    settings = DeckSettings(
        nlgeom=True,
        increments=20,
        reaction_sets=root,
        field_output_frequency=1,
        contact_pairs=[pair],
        point_loads=[
            PointLoad(node_set=tip[0], force=(0.0, 0.0, -applied), total=True,
                      description="load driving the beam onto the stop")
        ],
    )
    boundary = [BoundaryCondition(n, (1, 2, 3), 0.0, "beam root fixed") for n in root]
    boundary += [
        BoundaryCondition(n, (1, 2, 3), 0.0, "shelf fully fixed") for n in shelf_base
    ]

    result = submit(mesh, boundary, settings, "Phase 6: mechanical stop",
                    solver, archive)
    if not result.is_trustworthy:
        return BenchmarkOutcome(
            Capability.MECHANICAL_STOPS, False,
            "The mechanical-stop run did not produce a trustworthy solution.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )

    displacements = node_displacements(result, mesh)
    if displacements is None:
        return BenchmarkOutcome(
            Capability.MECHANICAL_STOPS, False,
            "No displacement field was written.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )
    at_tip = (mesh.nodes[:, 0] > length - TOL) & (mesh.nodes[:, 2] > -TOL)
    measured = float(np.abs(displacements[at_tip, 2]).max())
    tolerance = 0.15
    error = (measured - STOP_GAP) / STOP_GAP
    return BenchmarkOutcome(
        Capability.MECHANICAL_STOPS,
        abs(error) <= tolerance,
        (
            f"Beam stiffness {stiffness:.4g} N/mm, gap {STOP_GAP} mm, so "
            f"{contact_force:.4g} N just closes it. Loaded to {applied:.4g} N, which "
            f"without a stop would give {3 * STOP_GAP:.2f} mm. Tip deflection "
            f"{measured:.4g} mm against the {STOP_GAP} mm gap "
            f"({error * 100:+.1f} %)."
        ),
        measured=measured, expected=STOP_GAP, tolerance=tolerance,
        convergence=result.convergence.summary,
        run_directory=str(result.run_directory),
    )


def benchmark_self_contact(solver, archive) -> BenchmarkOutcome:
    """A hairpin strip pressed closed until its two legs meet.

    The hardest of the five, and the one that took three attempts to pose correctly.
    Both failures are worth writing down because neither was a solver problem.

    **Attempt one** declared every surface of the part as both slave and master,
    which is the textbook way to set up self-contact and here meant every node began
    in contact with the face it belongs to. It diverged in the first increment.
    Naming the two walls that can actually meet is cheaper and better posed, and the
    hairpin's geometry says exactly which they are.

    **Attempt two** drove the upper leg's free end with a *prescribed displacement*
    larger than the gap. A prescribed displacement is not something contact can
    resist: the node goes where it is told, and it took the leg straight through the
    other one. The run converged, the closest approach came out at exactly minus the
    overshoot, and the 129 cutbacks were the only sign anything was wrong. It is the
    cleanest illustration this project has produced of a converged, warning-free,
    entirely meaningless result -- and the cause was the boundary condition, not the
    contact formulation, which is why "contact does not work here" would have been
    the wrong conclusion to record.

    The load is therefore a **force**, which contact can balance. Without contact the
    hairpin would close far past its gap; with it the legs stop on each other.
    """
    from barnes_ui.core.flexure.templates.meander import (
        MeanderParameters,
        build_meander,
    )

    parameters = MeanderParameters(
        run_length=20.0, n_runs=2, pitch=2.5, width=1.5, thickness=2.0
    )
    gap = parameters.pitch - parameters.width       # 1.0 mm of clear air

    # A leg bending in-plane has I = thickness * width^3 / 12, so a cantilever of
    # this length is worth roughly 0.21 N/mm. A 1 N push would close about 4.7 mm
    # free, against a 1.0 mm gap -- enough margin that a stop which is not engaging
    # is unmistakable, and small enough that the material stays in a sane range.
    inertia = parameters.thickness * parameters.width ** 3 / 12.0
    leg_stiffness = 3.0 * E_MPA * inertia / parameters.run_length ** 3
    push_force = 1.0

    mesh = generate_mesh(
        build_meander(parameters),
        MeshSettings(element_size=0.9, second_order=True),
        smallest_dimension=parameters.width,
    )

    half = parameters.width / 2.0
    # The facing walls: the top of the lower run and the bottom of the upper one.
    lower_wall = surfaces_where(mesh, lambda p: abs(p[1] - half) < 1e-4)
    upper_wall = surfaces_where(
        mesh, lambda p: abs(p[1] - (parameters.pitch - half)) < 1e-4
    )
    # Free ends, both at x = 0; the turn is at the far end.
    lower_end = surfaces_where(mesh, lambda p: p[0] < TOL and p[1] < half + 1e-4)
    upper_end = surfaces_where(
        mesh, lambda p: p[0] < TOL and p[1] > parameters.pitch - half - 1e-4
    )
    missing = [
        label for label, sets in (
            ("lower facing wall", lower_wall), ("upper facing wall", upper_wall),
            ("lower free end", lower_end), ("upper free end", upper_end),
        ) if not sets
    ]
    if missing:
        return BenchmarkOutcome(
            Capability.SELF_CONTACT, False,
            f"Could not identify the {', '.join(missing)} on the hairpin, so the "
            "benchmark could not be set up.",
        )

    attempted: list[str] = []
    result = None
    label = ""
    for label, formulation, factor in CONTACT_ATTEMPTS:
        slave_kind = (
            SurfaceType.ELEMENT
            if formulation is ContactFormulation.SURFACE_TO_SURFACE
            else SurfaceType.NODE
        )
        pair = ContactPair(
            name="self",
            slave=ContactSurface.from_node_sets(
                mesh, upper_wall, "self_slave", slave_kind
            ),
            master=ContactSurface.from_node_sets(
                mesh, lower_wall, "self_master", SurfaceType.ELEMENT
            ),
            formulation=formulation,
            stiffness=factor * E_MPA / mesh.element_size,
            self_contact=True,
        )
        settings = DeckSettings(
            nlgeom=True,
            increments=60,
            initial_increment=0.01,
            minimum_increment=1.0e-8,
            maximum_increment=0.05,
            reaction_sets=lower_end,
            field_output_frequency=1,
            contact_pairs=[pair],
            point_loads=[
                PointLoad(
                    node_set=upper_end[0], force=(0.0, -push_force, 0.0), total=True,
                    description="force closing the hairpin",
                )
            ],
        )
        boundary = [
            BoundaryCondition(n, (1, 2, 3), 0.0, "lower leg's free end fixed")
            for n in lower_end
        ]
        result = submit(
            mesh, boundary, settings,
            f"Phase 6: hairpin self-contact, {label}", solver, archive,
        )
        attempted.append(f"{label}: {result.convergence.summary}")
        if result.is_trustworthy:
            break
    else:
        return BenchmarkOutcome(
            Capability.SELF_CONTACT, False,
            (
                f"The hairpin did not converge in any configuration under a "
                f"{push_force} N closing force on a {gap:.1f} mm gap. Attempts: "
                + "; ".join(attempted)
                + ". Phase 6 permits this outcome: it is a statement about what this "
                "toolchain can do, not a gap to paper over. Every deck and solver "
                "log is archived."
            ),
            convergence=attempted[-1] if attempted else "",
            run_directory=str(result.run_directory) if result else None,
        )

    displacements = node_displacements(result, mesh)
    if displacements is None:
        return BenchmarkOutcome(
            Capability.SELF_CONTACT, False, "No displacement field was written.",
            convergence=result.convergence.summary,
            run_directory=str(result.run_directory),
        )

    # Measure over the straight runs only, clear of both ends.
    #
    # The turn at the far end spans the whole pitch, so classifying nodes by their
    # original y puts part of the turn in each group. As the hairpin closes the turn
    # deforms, and the "upper" part of it legitimately moves past the "lower" part --
    # which is the turn bending, not the legs interpenetrating. Including it reported
    # 0.215 mm of apparent penetration on a run whose true penalty penetration, at
    # this pressure and stiffness, is of order a micron.
    straight = (mesh.nodes[:, 0] > 1.0) & (
        mesh.nodes[:, 0] < parameters.run_length - 1.0
    )
    deformed = mesh.nodes + displacements
    lower = deformed[straight & (mesh.nodes[:, 1] < half + 1e-4)]
    upper = deformed[straight & (mesh.nodes[:, 1] > parameters.pitch - half - 1e-4)]
    separation = float(upper[:, 1].min() - lower[:, 1].max())
    closure = gap - separation
    tolerance = 0.05 * mesh.element_size
    passed = separation > -tolerance and closure > 0.5 * gap

    return BenchmarkOutcome(
        Capability.SELF_CONTACT,
        passed,
        (
            f"Converged with {label}. Attempts: " + "; ".join(attempted) + ". "
            f"Hairpin with a {gap:.1f} mm clear gap, closed by a {push_force} N "
            f"force against a leg stiffness of about {leg_stiffness:.3g} N/mm -- "
            f"enough to close roughly {push_force / leg_stiffness:.1f} mm if nothing "
            f"stopped it. Closest approach after the solve {separation:+.4g} mm, so "
            f"the gap closed by {closure:.4g} mm and the legs stopped on each other. "
            f"Element size {mesh.element_size:.3g} mm, penetration tolerance "
            f"{tolerance:.3g} mm."
        ),
        measured=separation, expected=0.0, tolerance=tolerance,
        convergence=result.convergence.summary,
        run_directory=str(result.run_directory),
    )


BENCHMARKS: dict[Capability, Callable[..., BenchmarkOutcome]] = {
    Capability.GRAVITY: benchmark_gravity,
    Capability.TENDON_LOAD: benchmark_tendon,
    Capability.CONTACT_FRICTIONLESS: lambda s, a: benchmark_contact(s, a, 0.0),
    Capability.CONTACT_FRICTION: lambda s, a: benchmark_contact(s, a, 0.3),
    Capability.MECHANICAL_STOPS: benchmark_mechanical_stop,
    Capability.SELF_CONTACT: benchmark_self_contact,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only", nargs="+", default=None,
        choices=[c.value for c in BENCHMARKS],
        help="Run only these benchmarks (default: all).",
    )
    parser.add_argument("--archive", type=Path, default=None)
    parser.add_argument(
        "--registry", type=Path, default=None,
        help="Where to write the capability registry.",
    )
    args = parser.parse_args(argv)

    solver = find_solver()
    if solver is None:
        raise SystemExit(
            "CalculiX was not found, so no capability can be demonstrated. See "
            "docs/08-calculix-installation.md."
        )
    solver = probe_solver(solver)
    print(solver.describe(), flush=True)

    registry = CapabilityRegistry.load(args.registry)

    selected = (
        [Capability(value) for value in args.only] if args.only
        else list(BENCHMARKS)
    )
    for capability in selected:
        print(f"\n=== {capability.label} ===", flush=True)
        print(capability.benchmark_description, flush=True)
        try:
            outcome = BENCHMARKS[capability](solver, args.archive)
        except Exception as exc:  # noqa: BLE001 - a crash is a benchmark result
            outcome = BenchmarkOutcome(
                capability, False,
                f"The benchmark raised {type(exc).__name__}: {exc}",
            )
        registry.set(outcome.to_record(solver.version))
        print(registry.record(capability).summary(), flush=True)

    written = registry.save(args.registry)
    print(f"\nWrote {written}", flush=True)
    print(registry.summary(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
