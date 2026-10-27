"""CalculiX input deck generation.

The deck is a text artefact, archived verbatim with every run. That is deliberate:
anyone can open ``input.inp`` and read exactly what was solved, without trusting the
code that produced it. For a tool whose numbers feed design decisions, an auditable
input is worth more than a convenient API.

Material parameter conversion
-----------------------------

CalculiX hyperelastic models take a compressibility parameter ``D1`` alongside the
deviatoric constants, where ``D1 = 2 / K`` and ``K`` is the bulk modulus. The project's
material models carry a Poisson's ratio instead, so the conversion happens here, once,
with the algebra written out.

For a Neo-Hookean solid with initial shear modulus ``mu``:

    K / mu = (2 + 2*nu) / (3 - 6*nu)

which for the near-incompressible default ``nu = 0.4995`` gives ``K = 999.67 * mu``.
``D1`` cannot be zero -- true incompressibility is not representable with displacement
elements -- so a near-incompressible value is used and the resulting Poisson's ratio is
recorded in the deck as a comment.

Verification status
-------------------

**The keyword syntax here follows the CalculiX user manual but has not yet been
executed against a real solver**, because CalculiX is not installed on the development
machine. Until a run confirms it, this generator is unverified: the structure is
tested, the physics it encodes is reviewed, but "CalculiX accepts this deck" is not yet
a fact. The `*RIGID BODY` rotational driving in particular uses a convention that needs
confirming against a real run. Nothing in the application presents results from an
unexecuted deck, so the risk is a failed run rather than a wrong number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..material.models import HyperelasticModel, MaterialModelKind
from .meshing import Mesh

logger = logging.getLogger(__name__)

__all__ = ["BoundaryCondition", "RigidBody", "DeckSettings", "write_deck", "DeckError"]


class DeckError(ValueError):
    """The requested analysis cannot be expressed as a CalculiX deck."""


@dataclass
class BoundaryCondition:
    """A constraint on a named node set.

    ``dofs`` are CalculiX degrees of freedom: 1-3 translation, 4-6 rotation (the latter
    only meaningful on a rigid-body reference node).
    """

    node_set: str
    dofs: Sequence[int]
    value: float = 0.0
    description: str = ""


@dataclass
class RigidBody:
    """A node set tied to a rigid reference, so a rotation can be prescribed on it.

    This is how a joint rotation is driven. A finger joint rotates the distal phalanx
    rigidly about its axis, so the flexure's distal attachment has to follow that
    rotation exactly -- which is a single kinematic condition on a whole set of nodes,
    not something expressible as per-node displacements without computing each one.

    CalculiX's ``*RIGID BODY`` takes a reference node carrying the translations and a
    rotation node whose degrees of freedom 1-3 are the rotations about the global axes.
    Both are extra nodes appended after the mesh, and the reference node must lie **on
    the joint axis**, or the prescribed rotation is about the wrong line.

    Reading the reaction moment off the rotation node is what makes the torque-angle
    workflow possible at all: it concentrates a distributed reaction into one point
    where the moment is exact, rather than requiring per-node forces.
    """

    #: The mesh node set or sets to tie. A whole attachment region generally spans many
    #: surfaces -- the A3 flexure's distal collar is 62 of them -- and tying only one of
    #: them leaves the rest free. Doing exactly that produced a result wrong by a factor
    #: of 63; see the note on ``node_sets`` below.
    node_sets: Sequence[str] | str
    #: A point on the joint axis, in mm. Becomes the rigid body's reference node.
    reference_point: tuple[float, float, float]
    #: Name given to the generated reference node set, for boundary conditions.
    name: str = "rigid"

    #: Hold the reference node against translation, so the body rotates about the joint
    #: axis instead of floating.
    #:
    #: Default True, and it is the default because the alternative was a trap. The
    #: reference node sits on the joint axis; a finger's distal phalanx rotates about
    #: that axis and does not translate. With these degrees of freedom left free, the
    #: A3 flexure's distal collar was prescribed a 2-degree rotation and simply
    #: translated to relieve almost all of the strap deformation. The run converged,
    #: reported a perfectly linear reaction history, raised no warnings -- and made the
    #: flexure appear roughly 55 times softer than the beam model.
    #:
    #: Set it False only for a body that genuinely is free to translate, and say why.
    pin_reference: bool = True

    #: Filled in by the deck writer: the one-based node numbers it allocated.
    reference_node: int = 0
    rotation_node: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.node_sets, str):
            self.node_sets = [self.node_sets]
        if not self.node_sets:
            raise DeckError(
                f"Rigid body {self.name!r} ties no node sets. A rigid body with no "
                "members constrains nothing."
            )

    @property
    def member_set_name(self) -> str:
        """Name of the combined set the writer generates for the tied nodes."""
        return f"{self.name}_members"

    @property
    def reference_set_name(self) -> str:
        """Name of the one-node set holding the reference node.

        Callers need this to name the set in ``DeckSettings.reaction_sets`` and to
        read the reaction back out of the result, so it is a property rather than a
        convention each caller re-spells.
        """
        return f"{self.name}_ref"

    @property
    def rotation_set_name(self) -> str:
        """Name of the one-node set holding the rotation node.

        This is where a prescribed joint rotation is applied and where the reaction
        *moment* appears -- CalculiX reports a rotation node's moments in the force
        slots, so component 0 of its reaction is the moment about X.
        """
        return f"{self.name}_rot"


@dataclass
class DeckSettings:
    """Everything needed to turn a mesh and a material into a deck."""

    #: Large-deformation kinematics. Off only for the linear benchmark.
    nlgeom: bool = True
    #: Number of increments the step is divided into.
    increments: int = 20
    #: Initial increment as a fraction of the step.
    initial_increment: float = 0.05
    minimum_increment: float = 1.0e-5
    maximum_increment: float = 0.2
    #: Node sets whose reaction forces are printed to the .dat file.
    #:
    #: Always written at every increment. This is the torque history the torque-angle
    #: workflow is built on, and it is a few hundred bytes of text per increment.
    reaction_sets: list[str] = field(default_factory=list)

    #: How often to write displacement/stress/strain fields to the .frd file, in
    #: increments. ``None`` means **no field output at all**, which is the default.
    #:
    #: Field output is expensive and is off by default because leaving it on cost a
    #: real run dearly. Requesting ``*NODE FILE`` and ``*EL FILE`` with no frequency
    #: control writes a full snapshot of every node and element on *every* increment.
    #: On the A3 twin-strap flexure -- 61,021 nodes, and an increment size that
    #: collapsed to 0.0105 so the step needed roughly 95 increments -- the .frd file
    #: reached 462 MB at increment 26 and was heading for about 1.8 GB, for an analysis
    #: whose actual output is a single reaction moment per increment.
    #:
    #: Set it to 1 to visualise a deformation, or to a larger number to sample the
    #: motion. For a torque-angle sweep, leave it as None: the reaction history in the
    #: .dat file is the result, and the fields are not looked at.
    field_output_frequency: int | None = None

    #: Rigid bodies, for prescribing a joint rotation on an attachment region.
    rigid_bodies: list[RigidBody] = field(default_factory=list)

    #: Phase 6. Contact pairs, each carrying its two surfaces.
    #:
    #: Writing these cards is not the same as the capability working. Nothing in this
    #: module claims contact converges on real geometry; that claim is made only by
    #: core/fea/capabilities.py, and only from a benchmark recorded on the machine in
    #: question.
    contact_pairs: list[Any] = field(default_factory=list)

    #: Phase 6. A uniform body acceleration. Requires a density, which the load
    #: carries -- the material model deliberately has no default density.
    gravity: Any = None

    #: Phase 6. Concentrated forces, for tendon loading.
    point_loads: list[Any] = field(default_factory=list)


def write_deck(
    mesh: Mesh,
    material: HyperelasticModel,
    boundary_conditions: Sequence[BoundaryCondition],
    settings: DeckSettings | None = None,
    title: str = "Barnes UI analysis",
) -> str:
    """Build a CalculiX input deck as a string.

    Node and element numbering is one-based here; the mesh carries zero-based indices
    and the offset is applied in exactly this one place.
    """
    settings = settings or DeckSettings()

    if mesh.element_count == 0:
        raise DeckError("The mesh has no elements.")
    if not boundary_conditions:
        raise DeckError(
            "No boundary conditions were supplied. An unconstrained model has rigid "
            "body modes and will not solve."
        )

    # Rigid bodies allocate extra nodes, so their generated set names are legitimate
    # boundary-condition targets even though they are not mesh surfaces.
    generated_sets = set()
    next_node = mesh.node_count + 1
    for body in settings.rigid_bodies:
        unknown = [s for s in body.node_sets if s not in mesh.node_sets]
        if unknown:
            raise DeckError(
                f"Rigid body {body.name!r} references node set(s) {unknown}, which are "
                f"not in the mesh. Available: {sorted(mesh.node_sets)}"
            )
        body.reference_node = next_node
        body.rotation_node = next_node + 1
        next_node += 2
        generated_sets.add(f"{body.name}_ref")
        generated_sets.add(f"{body.name}_rot")
        generated_sets.add(body.member_set_name)

    known = set(mesh.node_sets) | generated_sets
    missing = [bc.node_set for bc in boundary_conditions if bc.node_set not in known]
    if missing:
        raise DeckError(
            f"Boundary conditions reference node sets that are not in the mesh: "
            f"{missing}. Available: {sorted(known)}"
        )

    lines: list[str] = []
    out = lines.append

    out(f"** {title}")
    out("** Generated by Barnes UI. This deck is archived with the run so that the")
    out("** analysis can be inspected without trusting the code that wrote it.")
    out(f"** Mesh: {mesh.describe()}")
    out(f"** Material: {material.describe()}")
    out(f"** Material provenance: {material.provenance.label}")
    for caveat in material.caveats:
        out(f"**   CAVEAT: {caveat.message}")
    out("**")

    _write_nodes(out, mesh, settings)
    _write_elements(out, mesh)
    _write_node_sets(out, mesh, boundary_conditions, settings)
    _write_rigid_bodies(out, mesh, settings)
    _write_contact_surfaces(out, mesh, settings)
    _write_material(out, material, settings)
    _write_contact_interactions(out, settings)
    _write_step(out, mesh, boundary_conditions, settings)

    return "\n".join(lines) + "\n"


def _write_nodes(out, mesh: Mesh, settings: DeckSettings) -> None:
    out("*NODE, NSET=Nall")
    for index, (x, y, z) in enumerate(mesh.nodes, start=1):
        out(f"{index}, {x:.9g}, {y:.9g}, {z:.9g}")

    # Rigid-body reference and rotation nodes, appended after the mesh. The reference
    # node sits on the joint axis; the rotation node's position is immaterial to
    # CalculiX but is placed alongside it so a viewer shows them together.
    for body in settings.rigid_bodies:
        x, y, z = body.reference_point
        out(f"** rigid body {body.name}: reference node on the joint axis")
        out(f"{body.reference_node}, {x:.9g}, {y:.9g}, {z:.9g}")
        out(f"** rigid body {body.name}: rotation node (DOFs 1-3 are rotations)")
        out(f"{body.rotation_node}, {x:.9g}, {y:.9g}, {z:.9g}")


def _write_rigid_bodies(out, mesh: Mesh, settings: DeckSettings) -> None:
    for body in settings.rigid_bodies:
        out(f"*NSET, NSET={body.reference_set_name}")
        out(f"{body.reference_node}")
        out(f"*NSET, NSET={body.rotation_set_name}")
        out(f"{body.rotation_node}")

        # One combined set covering every tied surface. An attachment region is
        # generally many surfaces, and tying one of them is not an approximation of
        # tying all of them -- it is a different structure. Driving 1 of the A3's 62
        # distal collar surfaces, while fixing all 60 proximal ones, produced an
        # apparent flexure stiffness 63 times softer than the beam model and took 90
        # convergence cutbacks to get there. The severe cutback count was the clue: a
        # single facet being rotated against an otherwise free collar is badly
        # conditioned, not merely compliant.
        indices = np.unique(
            np.concatenate([np.asarray(mesh.node_sets[s]).ravel() for s in body.node_sets])
        )
        out(f"*NSET, NSET={body.member_set_name}")
        ids = [str(int(i) + 1) for i in indices]
        for start in range(0, len(ids), 8):
            out(", ".join(ids[start:start + 8]) + ("," if start + 8 < len(ids) else ""))

        out(
            f"*RIGID BODY, NSET={body.member_set_name}, "
            f"REF NODE={body.reference_node}, ROT NODE={body.rotation_node}"
        )


#: Permutation from Gmsh's 10-node tetrahedron ordering to CalculiX's C3D10.
#:
#: The two conventions agree on the four corners and on the first four mid-edge nodes,
#: then disagree on the last two:
#:
#:     position   Gmsh        CalculiX / Abaqus
#:        8       mid(2,3)    mid(1,3)
#:        9       mid(1,3)    mid(2,3)
#:
#: So positions 8 and 9 are swapped. This is not cosmetic. A 10-node tetrahedron's
#: Jacobian depends on all ten node positions, and misplacing two mid-edge nodes folds
#: the element: the first real submission to CalculiX failed with
#: "*ERROR in e_c3d: nonpositive jacobian" on element after element, despite every
#: element having a positive corner volume by the project's own quality check. The
#: corner orientation was fine all along; the mid-side nodes were not.
_GMSH_TO_CALCULIX_TET10 = (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)


def _write_elements(out, mesh: Mesh) -> None:
    out(f"*ELEMENT, TYPE={mesh.calculix_element_type}, ELSET=Eall")

    for index, connectivity in enumerate(mesh.elements, start=1):
        if mesh.second_order:
            ordered = [connectivity[i] for i in _GMSH_TO_CALCULIX_TET10]
        else:
            ordered = list(connectivity)

        node_ids = [str(int(n) + 1) for n in ordered]
        # CalculiX limits an input line's length, so long C3D10 rows are continued.
        if len(node_ids) > 8:
            out(f"{index}, {', '.join(node_ids[:8])},")
            out(f"{', '.join(node_ids[8:])}")
        else:
            out(f"{index}, {', '.join(node_ids)}")


def _write_node_sets(
    out,
    mesh: Mesh,
    boundary_conditions: Sequence[BoundaryCondition],
    settings: DeckSettings,
) -> None:
    # Rigid-body *member* sets must be written here. Omitting them produced the most
    # instructive failure of this phase: CalculiX reported only
    # "*WARNING reading *RIGID BODY: node set ... does not exist", carried on, solved a
    # model with nothing tied and nothing loaded, and reported CONVERGED with every
    # displacement and every reaction exactly zero. A converged run on a null problem.
    #
    # The rigid body's own reference and rotation node sets are written by
    # _write_rigid_bodies; it is the set of mesh nodes being tied that belongs here.
    # Point loads name a node set too, and a set that is referenced but never
    # defined is a fatal *ERROR in CalculiX rather than a warning -- which at least
    # fails loudly, unlike the rigid-body case above. Collecting every referencing
    # card in one place is what stops the next kind of reference from being missed.
    needed = (
        {bc.node_set for bc in boundary_conditions}
        | set(settings.reaction_sets)
        | {load.node_set for load in settings.point_loads}
    )
    for name in sorted(needed):
        indices = mesh.node_sets.get(name)
        if indices is None:
            continue
        out(f"*NSET, NSET={name}")
        ids = [str(int(i) + 1) for i in np.asarray(indices).ravel()]
        for start in range(0, len(ids), 8):
            out(", ".join(ids[start:start + 8]) + ("," if start + 8 < len(ids) else ""))


def _write_density(out, settings: DeckSettings | None) -> None:
    """``*DENSITY``, written only when a body load actually needs it.

    Not written otherwise, because a density nobody supplied would have to be
    invented, and a static analysis without body loads does not use one.
    """
    if settings is None or settings.gravity is None:
        return
    out("** Density in tonnes per cubic millimetre: the mass unit implied by")
    out("** millimetres, newtons and seconds. A polymer is around 1.2e-9 here.")
    out("*DENSITY")
    out(f"{settings.gravity.density:.9g}")


def _write_material(out, material: HyperelasticModel,
                    settings: DeckSettings | None = None) -> None:
    name = "TPU"
    out(f"*MATERIAL, NAME={name}")

    if material.kind is MaterialModelKind.LINEAR_ELASTIC:
        modulus, poisson = material.parameters
        out("*ELASTIC")
        out(f"{modulus:.9g}, {poisson:.9g}")
    else:
        keyword = material.kind.calculix_keyword
        if keyword is None:
            raise DeckError(
                f"{material.kind.label} has no CalculiX equivalent. Supported: "
                "Neo-Hookean, Mooney-Rivlin, Ogden."
            )
        d1 = _compressibility_parameter(material)
        out(f"**   D1 = {d1:.9g} corresponds to a Poisson's ratio of "
            f"{material.poisson_ratio:.6f}")
        out("**   D1 cannot be zero: true incompressibility is not representable with")
        out("**   displacement elements, so a near-incompressible value is used.")

        if material.kind is MaterialModelKind.NEO_HOOKEAN:
            out(f"*HYPERELASTIC, {keyword}")
            out(f"{material.parameters[0]:.9g}, {d1:.9g}")
        elif material.kind is MaterialModelKind.MOONEY_RIVLIN:
            out(f"*HYPERELASTIC, {keyword}")
            out(f"{material.parameters[0]:.9g}, {material.parameters[1]:.9g}, {d1:.9g}")
        elif material.kind is MaterialModelKind.OGDEN_1:
            out(f"*HYPERELASTIC, {keyword}, N=1")
            out(f"{material.parameters[0]:.9g}, {material.parameters[1]:.9g}, {d1:.9g}")
        elif material.kind is MaterialModelKind.OGDEN_2:
            mu1, a1, mu2, a2 = material.parameters
            out(f"*HYPERELASTIC, {keyword}, N=2")
            out(f"{mu1:.9g}, {a1:.9g}, {mu2:.9g}, {a2:.9g}, {d1:.9g}, 0.")
        else:  # pragma: no cover - guarded by calculix_keyword above
            raise DeckError(f"Unhandled material kind {material.kind}")

    _write_density(out, settings)
    out("*SOLID SECTION, ELSET=Eall, MATERIAL=" + name)


def _compressibility_parameter(material: HyperelasticModel) -> float:
    """CalculiX ``D1`` from the model's Poisson's ratio.

    ``D1 = 2 / K`` and, for an initial shear modulus ``mu``,
    ``K = mu * (2 + 2*nu) / (3 - 6*nu)``.

    A Poisson's ratio of exactly 0.5 gives an infinite bulk modulus and a zero ``D1``,
    which is why the material models default to 0.4995 rather than 0.5.
    """
    nu = material.poisson_ratio
    if nu >= 0.5:
        raise DeckError(
            f"Poisson's ratio of {nu} implies infinite bulk modulus, which cannot be "
            "expressed as a CalculiX D1. Use a near-incompressible value such as "
            "0.4995."
        )
    mu = material.initial_shear_modulus
    bulk = mu * (2.0 + 2.0 * nu) / (3.0 - 6.0 * nu)
    if bulk <= 0:
        raise DeckError("Computed a non-positive bulk modulus from the material.")
    return 2.0 / bulk


def _write_contact_surfaces(out, mesh: Mesh, settings: DeckSettings) -> None:
    """Write every surface referenced by a contact pair, once each.

    A surface used as both a master and a slave -- which is exactly what
    self-contact is -- must still be written only once, or CalculiX reports a
    duplicate definition and stops.
    """
    if not settings.contact_pairs:
        return

    from .contact import SurfaceType

    written: set[str] = set()
    for pair in settings.contact_pairs:
        for surface in (pair.slave, pair.master):
            if surface.name in written:
                continue
            written.add(surface.name)
            out(f"*SURFACE, NAME={surface.name}, TYPE={surface.kind.value}")
            if surface.kind is SurfaceType.NODE:
                # One node per line. *SURFACE is not *NSET: CalculiX reads a surface
                # definition as one entry per line and rejects the eight-per-line
                # packing that node sets use, with
                # "*ERROR reading *SURFACE: only one entry per line".
                for index in surface.nodes:
                    out(f"{int(index) + 1}")
            else:
                for element, face in surface.faces:
                    out(f"{element + 1}, {face}")


def _write_contact_interactions(out, settings: DeckSettings) -> None:
    """Surface interactions and contact pairs.

    Written after the material block and before the step, which is where CalculiX
    expects model-level cards.
    """
    for pair in settings.contact_pairs:
        interaction = f"{pair.name}_interaction"
        out(f"*SURFACE INTERACTION, NAME={interaction}")
        out("*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR")
        if pair.stiffness <= 0.0:
            raise DeckError(
                f"Contact pair {pair.name!r} has no normal stiffness. A linear "
                "pressure-overclosure law with zero stiffness lets the surfaces pass "
                "through each other while the run converges happily. Use "
                "ContactPair.suggested_stiffness() as a starting point and check the "
                "penetration."
            )
        out(f"{pair.stiffness:.9g}")
        if pair.friction > 0.0:
            out("*FRICTION")
            out(f"{pair.friction:.9g}, {pair.resolved_stick_stiffness():.9g}")
        out(f"** {pair.describe()}")
        out(
            f"*CONTACT PAIR, INTERACTION={interaction}, "
            f"TYPE={pair.formulation.value}"
        )
        out(f"{pair.slave.name}, {pair.master.name}")


def _write_loads(out, mesh: Mesh, settings: DeckSettings) -> None:
    """Body and concentrated loads, inside the step."""
    gravity = settings.gravity
    if gravity is not None:
        x, y, z = gravity.unit_direction
        out(f"** {gravity.describe()}")
        out("*DLOAD")
        out(
            f"{gravity.element_set}, GRAV, {gravity.magnitude:.9g}, "
            f"{x:.9g}, {y:.9g}, {z:.9g}"
        )

    if settings.point_loads:
        out("*CLOAD")
        for load in settings.point_loads:
            nodes = mesh.node_sets.get(load.node_set)
            if nodes is None:
                raise DeckError(
                    f"Point load references node set {load.node_set!r}, which is not "
                    f"in the mesh. Available: {sorted(mesh.node_sets)}"
                )
            components = load.per_node(len(nodes))
            out(f"** {load.describe()} over {len(nodes)} node(s)")
            for dof, value in enumerate(components, start=1):
                if value != 0.0:
                    out(f"{load.node_set}, {dof}, {value:.9g}")


def _write_step(
    out,
    mesh: Mesh,
    boundary_conditions: Sequence[BoundaryCondition],
    settings: DeckSettings,
) -> None:
    nlgeom = ", NLGEOM" if settings.nlgeom else ""
    out(f"*STEP{nlgeom}, INC={max(settings.increments * 10, 100)}")
    out("*STATIC")
    out(
        f"{settings.initial_increment:.9g}, 1.0, "
        f"{settings.minimum_increment:.9g}, {settings.maximum_increment:.9g}"
    )

    # Pin each rigid body's reference node unless the caller has already constrained it
    # or has explicitly opted out. Emitting it twice would be a duplicate boundary
    # condition, so an existing constraint on that set wins.
    already_constrained = {bc.node_set for bc in boundary_conditions}
    auto_pins: list[BoundaryCondition] = []
    for body in settings.rigid_bodies:
        reference_set = f"{body.name}_ref"
        if body.pin_reference and reference_set not in already_constrained:
            auto_pins.append(
                BoundaryCondition(
                    reference_set, (1, 2, 3), 0.0,
                    "reference node pinned on the joint axis so the body rotates "
                    "about it rather than translating",
                )
            )

    out("*BOUNDARY")
    for bc in list(boundary_conditions) + auto_pins:
        if bc.description:
            out(f"** {bc.description}")
        for dof in bc.dofs:
            out(f"{bc.node_set}, {dof}, {dof}, {bc.value:.9g}")

    _write_loads(out, mesh, settings)

    # Reaction forces go to the .dat file, which is the route used to extract the
    # restoring moment. Without this the run produces a deformed shape and no force.
    for name in settings.reaction_sets:
        out(f"*NODE PRINT, NSET={name}, TOTALS=ONLY")
        out("RF")

    if settings.field_output_frequency is not None:
        frequency = max(1, int(settings.field_output_frequency))
        out(f"*NODE FILE, FREQUENCY={frequency}")
        out("U, RF")
        out(f"*EL FILE, FREQUENCY={frequency}")
        out("S, E")
    else:
        out("** No field output requested. The reaction history above is the result;")
        out("** writing fields on every increment produced a 462 MB .frd on the A3")
        out("** flexure for an analysis whose output is one moment per increment.")

    out("*END STEP")
