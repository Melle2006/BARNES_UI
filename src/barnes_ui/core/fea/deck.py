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
from typing import Sequence

import numpy as np

from ..material.models import HyperelasticModel, MaterialModelKind
from .meshing import Mesh

logger = logging.getLogger(__name__)

__all__ = ["BoundaryCondition", "DeckSettings", "write_deck", "DeckError"]


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

    node_set: str
    #: A point on the joint axis, in mm. Becomes the rigid body's reference node.
    reference_point: tuple[float, float, float]
    #: Name given to the generated reference node set, for boundary conditions.
    name: str = "rigid"

    #: Filled in by the deck writer: the one-based node numbers it allocated.
    reference_node: int = 0
    rotation_node: int = 0


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
    reaction_sets: list[str] = field(default_factory=list)
    #: Request stress and strain fields in the .frd file.
    output_fields: bool = True
    #: Rigid bodies, for prescribing a joint rotation on an attachment region.
    rigid_bodies: list[RigidBody] = field(default_factory=list)


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
        if body.node_set not in mesh.node_sets:
            raise DeckError(
                f"Rigid body {body.name!r} references node set {body.node_set!r}, "
                f"which is not in the mesh. Available: {sorted(mesh.node_sets)}"
            )
        body.reference_node = next_node
        body.rotation_node = next_node + 1
        next_node += 2
        generated_sets.add(f"{body.name}_ref")
        generated_sets.add(f"{body.name}_rot")

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
    _write_rigid_bodies(out, settings)
    _write_material(out, material)
    _write_step(out, boundary_conditions, settings)

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


def _write_rigid_bodies(out, settings: DeckSettings) -> None:
    for body in settings.rigid_bodies:
        out(f"*NSET, NSET={body.name}_ref")
        out(f"{body.reference_node}")
        out(f"*NSET, NSET={body.name}_rot")
        out(f"{body.rotation_node}")
        out(
            f"*RIGID BODY, NSET={body.node_set}, "
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
    needed = (
        {bc.node_set for bc in boundary_conditions}
        | set(settings.reaction_sets)
        | {body.node_set for body in settings.rigid_bodies}
    )
    for name in sorted(needed):
        indices = mesh.node_sets.get(name)
        if indices is None:
            continue
        out(f"*NSET, NSET={name}")
        ids = [str(int(i) + 1) for i in np.asarray(indices).ravel()]
        for start in range(0, len(ids), 8):
            out(", ".join(ids[start:start + 8]) + ("," if start + 8 < len(ids) else ""))


def _write_material(out, material: HyperelasticModel) -> None:
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


def _write_step(
    out,
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

    out("*BOUNDARY")
    for bc in boundary_conditions:
        if bc.description:
            out(f"** {bc.description}")
        for dof in bc.dofs:
            out(f"{bc.node_set}, {dof}, {dof}, {bc.value:.9g}")

    # Reaction forces go to the .dat file, which is the route used to extract the
    # restoring moment. Without this the run produces a deformed shape and no force.
    for name in settings.reaction_sets:
        out(f"*NODE PRINT, NSET={name}, TOTALS=ONLY")
        out("RF")

    if settings.output_fields:
        out("*NODE FILE")
        out("U, RF")
        out("*EL FILE")
        out("S, E")

    out("*END STEP")
