"""Contact surfaces, contact pairs and friction for CalculiX decks.

Phase 6. Everything here writes deck cards; nothing here claims the cards work. That
claim is made only by :mod:`barnes_ui.core.fea.capabilities`, and only after a
benchmark has been run and recorded on the machine in question.

What CalculiX needs, and the part that is easy to get wrong
-----------------------------------------------------------

A contact pair is two surfaces plus an interaction. The slave surface may be a set of
nodes; the master surface must be made of *element faces*, because the contact
algorithm needs a normal and nodes do not have one.

Deriving element faces from a node set is where the subtlety is. A face belongs to the
surface when all of its nodes are in the set -- but for a second-order tetrahedron
"all of its nodes" means the three corners *and* the three mid-edge nodes, and the
mid-edge nodes of a C3D10 are not in any obvious positional relationship to the
corners unless you write the map down. :data:`_C3D10_FACES` writes it down, and
:func:`element_faces_from_nodes` checks the full six-node face rather than the corners
alone: a face selected on corners only will happily include a face whose mid-side
nodes belong to a different surface, producing a master surface with a hole in it that
nothing reports.

Face numbering follows CalculiX's own convention for tetrahedra, which matches
Abaqus's: S1 is the face opposite node 4, S2 opposite node 3, and so on. It is not the
same as Gmsh's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np

from .meshing import Mesh

logger = logging.getLogger(__name__)

__all__ = [
    "SurfaceType",
    "ContactSurface",
    "ContactFormulation",
    "ContactPair",
    "ContactError",
    "element_faces_from_nodes",
]


class ContactError(ValueError):
    """A contact definition that cannot be written or would not mean anything."""


#: Local node positions making up each face of a 4-node tetrahedron, in CalculiX's
#: face numbering. Zero-based positions into the element's connectivity.
_C3D4_FACES: dict[str, tuple[int, ...]] = {
    "S1": (0, 1, 2),
    "S2": (0, 3, 1),
    "S3": (1, 3, 2),
    "S4": (2, 3, 0),
}

#: The same four faces for a 10-node tetrahedron, including the mid-edge nodes.
#:
#: Positions 4-9 of a C3D10 are the mid-edge nodes of edges (1,2), (2,3), (3,1),
#: (1,4), (2,4), (3,4) in one-based corner numbering -- that is, zero-based:
#: 4 = mid(0,1), 5 = mid(1,2), 6 = mid(2,0), 7 = mid(0,3), 8 = mid(1,3), 9 = mid(2,3).
_C3D10_FACES: dict[str, tuple[int, ...]] = {
    "S1": (0, 1, 2, 4, 5, 6),
    "S2": (0, 3, 1, 7, 8, 4),
    "S3": (1, 3, 2, 8, 9, 5),
    "S4": (2, 3, 0, 9, 7, 6),
}


class SurfaceType(Enum):
    """Whether a surface is defined by nodes or by element faces."""

    NODE = "NODE"
    ELEMENT = "ELEMENT"


@dataclass
class ContactSurface:
    """One surface in a contact pair.

    Built from a mesh node set. A ``NODE`` surface stores the nodes; an ``ELEMENT``
    surface stores the ``(element, face)`` pairs derived from them.
    """

    name: str
    kind: SurfaceType
    #: Zero-based node indices, for a NODE surface.
    nodes: np.ndarray | None = None
    #: ``(zero-based element index, face label)`` pairs, for an ELEMENT surface.
    faces: list[tuple[int, str]] = field(default_factory=list)
    source_sets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind is SurfaceType.NODE:
            if self.nodes is None or len(self.nodes) == 0:
                raise ContactError(
                    f"Node surface {self.name!r} is empty. An empty slave surface "
                    "makes the contact pair silently do nothing."
                )
        elif not self.faces:
            raise ContactError(
                f"Element surface {self.name!r} has no faces. This usually means the "
                "node set it was built from does not cover any complete element face "
                "-- check that it is a surface set and not a scattered selection."
            )

    @property
    def size(self) -> int:
        return len(self.nodes) if self.kind is SurfaceType.NODE else len(self.faces)

    @classmethod
    def from_node_sets(
        cls, mesh: Mesh, names: Sequence[str] | str, surface_name: str,
        kind: SurfaceType = SurfaceType.ELEMENT,
    ) -> "ContactSurface":
        if isinstance(names, str):
            names = [names]
        unknown = [n for n in names if n not in mesh.node_sets]
        if unknown:
            raise ContactError(
                f"Surface {surface_name!r} references node set(s) {unknown}, not in "
                f"the mesh. Available: {sorted(mesh.node_sets)}"
            )
        nodes = np.unique(
            np.concatenate([np.asarray(mesh.node_sets[n]).ravel() for n in names])
        )
        if kind is SurfaceType.NODE:
            return cls(
                name=surface_name, kind=kind, nodes=nodes,
                source_sets=tuple(names),
            )
        return cls(
            name=surface_name, kind=kind,
            faces=element_faces_from_nodes(mesh, nodes),
            source_sets=tuple(names),
        )


def element_faces_from_nodes(
    mesh: Mesh, nodes: Sequence[int]
) -> list[tuple[int, str]]:
    """Every element face whose nodes all lie in ``nodes``.

    Returns zero-based element indices paired with CalculiX face labels. The caller
    adds the one-based offset when writing the deck, as everywhere else.
    """
    wanted = set(int(n) for n in np.asarray(nodes).ravel())
    faces = _C3D10_FACES if mesh.second_order else _C3D4_FACES

    found: list[tuple[int, str]] = []
    for index, connectivity in enumerate(mesh.elements):
        for label, positions in faces.items():
            if all(int(connectivity[p]) in wanted for p in positions):
                found.append((index, label))
    return found


class ContactFormulation(Enum):
    """Which contact discretisation to ask CalculiX for.

    NODE_TO_SURFACE
        The older, more robust formulation. Slave nodes are checked against master
        faces. Tolerant of mismatched meshes and of the large sliding a closing
        flexure produces.

    SURFACE_TO_SURFACE
        More accurate pressure distribution, more sensitive to mesh quality and
        considerably more fragile on large sliding.

    Node-to-surface is the default here, deliberately. Phase 6 is an investigation
    into whether contact converges at all on this geometry; starting with the fragile
    formulation would conflate "contact does not work" with "this formulation does
    not work".
    """

    NODE_TO_SURFACE = "NODE TO SURFACE"
    SURFACE_TO_SURFACE = "SURFACE TO SURFACE"


@dataclass
class ContactPair:
    """Two surfaces that may touch, and how they behave when they do.

    ``stiffness`` is the normal penalty stiffness in N/mm^3. There is no universally
    right value: too low and the surfaces interpenetrate visibly, too high and the
    solve will not converge. CalculiX's own guidance is to start from roughly the
    material's elastic modulus divided by a characteristic element size, which is what
    :meth:`suggested_stiffness` computes -- as a starting point to be checked by
    looking at the penetration, not as an answer.
    """

    name: str
    slave: ContactSurface
    master: ContactSurface
    formulation: ContactFormulation = ContactFormulation.NODE_TO_SURFACE
    #: Normal penalty stiffness, N/mm^3.
    stiffness: float = 0.0
    #: Coulomb friction coefficient. Zero means frictionless, which is a modelling
    #: choice and not an absence of one.
    friction: float = 0.0
    #: Tangential stick stiffness, N/mm^3. Defaults to stiffness/10 when left at zero,
    #: which is the usual rule of thumb.
    stick_stiffness: float = 0.0
    #: True when the pair is the flexure touching itself rather than another body.
    self_contact: bool = False

    def __post_init__(self) -> None:
        if self.master.kind is not SurfaceType.ELEMENT:
            raise ContactError(
                f"Contact pair {self.name!r}: the master surface must be made of "
                "element faces, because the contact algorithm needs a surface normal "
                "and a bare node set does not have one."
            )
        if self.friction < 0.0:
            raise ContactError(
                f"Contact pair {self.name!r}: a negative friction coefficient "
                f"({self.friction}) would add energy to the system."
            )
        if self.stiffness < 0.0:
            raise ContactError(
                f"Contact pair {self.name!r}: negative contact stiffness."
            )

    @staticmethod
    def suggested_stiffness(youngs_modulus: float, element_size: float) -> float:
        """A starting penalty stiffness, N/mm^3.

        ``E / h`` scaled up by a factor of ten, which is the commonly used starting
        point: stiff enough that penetration is a small fraction of an element, soft
        enough that the tangent matrix is not dominated by the contact terms.

        Check the resulting penetration. If it is a visible fraction of the geometry,
        the number was too low and the result is wrong in a way that converges
        cleanly.
        """
        if element_size <= 0.0:
            raise ContactError("Element size must be positive.")
        return 10.0 * youngs_modulus / element_size

    def resolved_stick_stiffness(self) -> float:
        return self.stick_stiffness or (self.stiffness / 10.0)

    def describe(self) -> str:
        kind = "self-contact" if self.self_contact else "pair"
        friction = (
            f"mu={self.friction:g}" if self.friction else "frictionless (mu=0)"
        )
        return (
            f"{self.name}: {kind}, {self.formulation.value}, "
            f"slave {self.slave.name} ({self.slave.size}), "
            f"master {self.master.name} ({self.master.size} faces), "
            f"K={self.stiffness:.4g} N/mm^3, {friction}"
        )
