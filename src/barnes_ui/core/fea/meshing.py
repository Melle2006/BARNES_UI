"""Mesh generation from B-rep geometry, via Gmsh.

Gmsh consumes an OpenCASCADE BREP shape directly, so the solid never has to be
round-tripped through a mesh format and re-healed.

Why second-order tetrahedra are the default and not an option
-------------------------------------------------------------

TPU is nearly incompressible: Poisson's ratio close to 0.5. First-order tetrahedra
under near-incompressibility **lock** -- they cannot represent the volume-preserving
deformation the material demands, so they resist it by stiffening, and report a part
as far stiffer than it is.

The dangerous part is that the run converges cleanly while doing it. There is no error,
no warning, no non-convergence; there is simply a wrong number. That is risk R7 in the
register, kept separate from general solver trouble precisely because it does not
announce itself.

Second-order tets (10-node, ``C3D10`` to CalculiX) have the kinematic richness to
avoid it. They cost more per element and are worth it. First-order output is available
only behind an explicit flag that the docstring argues against using.

Mesh sizing
-----------

The default targets a minimum number of elements through the thinnest dimension of the
part rather than a fixed length, because a 1 mm flexure and a 200 mm hand assembly need
very different absolute sizes and a fixed default would be wrong for both. Bending is
resolved by elements through the thickness, so that is the dimension that governs.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["Mesh", "MeshSettings", "generate_mesh", "MeshingError"]


class MeshingError(RuntimeError):
    """Mesh generation failed or produced something unusable."""


#: Elements through the thinnest dimension, by default.
#:
#: Three second-order elements through the thickness resolves a bending stress profile
#: adequately; two is marginal and one is useless for bending whatever the element
#: order. This is a starting point to be confirmed by a convergence study, never a
#: substitute for one.
DEFAULT_ELEMENTS_THROUGH_THICKNESS = 3


@dataclass
class MeshSettings:
    """Controls for mesh generation."""

    #: Target number of elements across the part's smallest dimension.
    elements_through_thickness: int = DEFAULT_ELEMENTS_THROUGH_THICKNESS
    #: Absolute element size in mm. Overrides the thickness-based rule when set.
    element_size: float | None = None
    #: Second order means 10-node tets. See the module docstring before changing it.
    second_order: bool = True
    #: Gmsh 3D algorithm. 1 = Delaunay, 10 = HXT (faster, parallel).
    algorithm_3d: int = 1
    #: Optimisation passes. Netgen optimisation markedly improves worst-element quality.
    optimise: bool = True
    verbose: bool = False

    def resolved_size(self, smallest_dimension: float) -> float:
        """Element size to request, in mm."""
        if self.element_size is not None:
            return float(self.element_size)
        if smallest_dimension <= 0:
            raise MeshingError(
                "The part has a zero smallest dimension, so an element size cannot be "
                "derived. Supply element_size explicitly."
            )
        return smallest_dimension / max(1, self.elements_through_thickness)


@dataclass
class Mesh:
    """A finite element mesh.

    ``nodes`` is (N, 3) float64 in mm. ``elements`` is (M, 10) for second-order tets or
    (M, 4) for first-order, holding **zero-based** node indices. CalculiX node and
    element numbering is one-based, and the deck writer adds the offset -- keeping the
    boundary in one place rather than scattering ``+1`` through the codebase.
    """

    nodes: np.ndarray
    elements: np.ndarray
    second_order: bool
    element_size: float
    #: Node indices on each named surface, for boundary conditions.
    node_sets: dict[str, np.ndarray] = field(default_factory=dict)
    quality: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return int(self.nodes.shape[0])

    @property
    def element_count(self) -> int:
        return int(self.elements.shape[0])

    @property
    def calculix_element_type(self) -> str:
        return "C3D10" if self.second_order else "C3D4"

    @property
    def nodes_per_element(self) -> int:
        return 10 if self.second_order else 4

    def describe(self) -> str:
        return (
            f"{self.element_count} {self.calculix_element_type} elements, "
            f"{self.node_count} nodes, target size {self.element_size:.4f} mm"
        )


def generate_mesh(
    shape: Any,
    settings: MeshSettings | None = None,
    smallest_dimension: float | None = None,
) -> Mesh:
    """Mesh a B-rep solid with Gmsh.

    ``smallest_dimension`` is the part's thinnest extent in mm, used to derive the
    element size. Taken from the bounding box when not supplied, which is right for a
    flexure whose thickness is its smallest bounding-box dimension and wrong for a part
    whose thin feature is interior -- in which case pass it explicitly.
    """
    settings = settings or MeshSettings()

    try:
        import gmsh
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise MeshingError(
            "The 'gmsh' package is required for meshing. Install it with: pip install gmsh"
        ) from exc

    from ..cad.export import write_brep
    from ..cad.inspect import bounding_box

    if smallest_dimension is None:
        smallest_dimension = bounding_box(shape).smallest_dimension

    size = settings.resolved_size(smallest_dimension)

    # Hand the geometry to Gmsh as BREP: it round-trips exactly, so nothing is lost
    # between the kernel and the mesher.
    scratch = Path(tempfile.mkdtemp(prefix="barnes_mesh_"))
    brep_path = scratch / "shape.brep"
    write_brep(shape, brep_path)

    # ``interruptible=False`` is not a preference. Gmsh's default initialise installs
    # its own SIGINT handler, and CPython refuses to set a signal handler from any
    # thread but the main one -- so the default raises ValueError("signal only works in
    # main thread of the main interpreter") the moment meshing is called from the GUI's
    # worker thread, which is the only place the GUI ever calls it from. The flag is
    # accepted by gmsh 4.11 onwards; older builds have no such handler to suppress, so
    # falling back to the bare call is correct rather than merely tolerable.
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1 if settings.verbose else 0)
        gmsh.model.add("barnes")
        gmsh.model.occ.importShapes(str(brep_path))
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(dim=3)
        if not volumes:
            raise MeshingError(
                "Gmsh found no volumes in the geometry. A surface model cannot be "
                "meshed for structural analysis -- re-export as a solid."
            )

        gmsh.option.setNumber("Mesh.MeshSizeMin", size * 0.4)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.Algorithm3D", settings.algorithm_3d)
        gmsh.option.setNumber("Mesh.Optimize", 1 if settings.optimise else 0)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 1 if settings.optimise else 0)
        # Curvature-driven refinement, so a tight turn's inner radius gets elements
        # rather than being cut across by a few large ones.
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)

        gmsh.model.mesh.generate(3)
        if settings.second_order:
            gmsh.model.mesh.setOrder(2)

        nodes, elements = _extract(gmsh, settings.second_order)
        surfaces = _surface_node_sets(gmsh, nodes)
    except MeshingError:
        raise
    except Exception as exc:
        raise MeshingError(f"Gmsh failed to mesh the geometry: {exc}") from exc
    finally:
        gmsh.finalize()

    if elements.shape[0] == 0:
        raise MeshingError(
            "Meshing produced no elements. The requested element size may be larger "
            "than the part."
        )

    mesh = Mesh(
        nodes=nodes,
        elements=elements,
        second_order=settings.second_order,
        element_size=size,
        node_sets=surfaces,
    )
    mesh.quality = _quality_metrics(mesh)
    mesh.notes.append(
        f"Element size {size:.4f} mm from {settings.elements_through_thickness} "
        f"element(s) through a smallest dimension of {smallest_dimension:.4f} mm."
    )
    if not settings.second_order:
        mesh.notes.append(
            "FIRST-ORDER ELEMENTS. For a nearly incompressible material these lock and "
            "report the part as far stiffer than it is, without any warning from the "
            "solver. Do not use this for TPU."
        )
    logger.info("Meshed: %s", mesh.describe())
    return mesh


def _extract(gmsh_module: Any, second_order: bool) -> tuple[np.ndarray, np.ndarray]:
    """Pull nodes and tetrahedra out of Gmsh into zero-based arrays."""
    node_tags, coords, _ = gmsh_module.model.mesh.getNodes()
    coords = np.asarray(coords, dtype=float).reshape(-1, 3)

    # Gmsh tags are arbitrary positive integers, not necessarily contiguous, so build
    # an explicit mapping rather than assuming tag == index + 1.
    tag_to_index = {int(tag): i for i, tag in enumerate(node_tags)}

    wanted = 11 if second_order else 4   # Gmsh type 11 = 10-node tet, 4 = 4-node tet
    types, element_tags, node_tags_per_type = gmsh_module.model.mesh.getElements(dim=3)

    collected: list[np.ndarray] = []
    per_element = 10 if second_order else 4
    for element_type, connectivity in zip(types, node_tags_per_type):
        if int(element_type) != wanted:
            continue
        block = np.asarray(connectivity, dtype=np.int64).reshape(-1, per_element)
        collected.append(block)

    if not collected:
        return coords, np.empty((0, per_element), dtype=np.int64)

    raw = np.vstack(collected)
    mapped = np.vectorize(tag_to_index.__getitem__)(raw)
    return coords, mapped.astype(np.int64)


def _surface_node_sets(gmsh_module: Any, nodes: np.ndarray) -> dict[str, np.ndarray]:
    """Node indices for each geometric surface, named by its Gmsh tag.

    Named by surface tag rather than by any guess at what the face is for. Which face
    is the fixed root and which is driven is a modelling decision the user makes, and
    the application must not infer it -- the same principle as joint axes.
    """
    node_tags, _, _ = gmsh_module.model.mesh.getNodes()
    tag_to_index = {int(tag): i for i, tag in enumerate(node_tags)}

    sets: dict[str, np.ndarray] = {}
    for dim, tag in gmsh_module.model.getEntities(dim=2):
        surface_tags, _, _ = gmsh_module.model.mesh.getNodes(dim, tag, includeBoundary=True)
        if len(surface_tags) == 0:
            continue
        indices = np.array(
            [tag_to_index[int(t)] for t in surface_tags if int(t) in tag_to_index],
            dtype=np.int64,
        )
        if indices.size:
            sets[f"surface_{tag}"] = np.unique(indices)
    return sets


def _quality_metrics(mesh: Mesh) -> dict[str, float]:
    """Element quality, reported so a bad mesh is visible rather than merely slow.

    Uses the signed volume of each tet's corner nodes. A negative or near-zero volume
    is an inverted or degenerate element, which will either stop the solver or quietly
    poison the result.
    """
    corners = mesh.elements[:, :4]
    p0, p1, p2, p3 = (mesh.nodes[corners[:, i]] for i in range(4))
    volumes = np.einsum("ij,ij->i", p1 - p0, np.cross(p2 - p0, p3 - p0)) / 6.0

    # Edge-length ratio as a shape measure: 1 for a regular tet, large for a sliver.
    edges = np.stack([
        np.linalg.norm(p1 - p0, axis=1), np.linalg.norm(p2 - p0, axis=1),
        np.linalg.norm(p3 - p0, axis=1), np.linalg.norm(p2 - p1, axis=1),
        np.linalg.norm(p3 - p1, axis=1), np.linalg.norm(p3 - p2, axis=1),
    ], axis=1)
    aspect = edges.max(axis=1) / np.maximum(edges.min(axis=1), 1e-30)

    return {
        "min_volume": float(volumes.min()),
        "mean_volume": float(volumes.mean()),
        "negative_volume_count": float(np.sum(volumes <= 0.0)),
        "max_edge_ratio": float(aspect.max()),
        "mean_edge_ratio": float(aspect.mean()),
        "poor_elements": float(np.sum(aspect > 20.0)),
    }
