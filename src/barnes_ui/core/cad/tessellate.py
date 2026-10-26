"""Triangulation of B-rep shapes for display.

The output of this module is for the viewport only. Nothing measured from a
tessellation is ever reported as a geometric measurement -- exact quantities come from
:mod:`barnes_ui.core.cad.inspect`, which integrates the analytic surfaces.

Keeping that boundary sharp matters. A triangle mesh of a curved flexure is a visual
approximation whose error depends on the deflection tolerance chosen here, and using
it to compute a bend radius would silently fold that tolerance into the result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from ._occ import occ, require_kernel, static

logger = logging.getLogger(__name__)

__all__ = ["TriangleMesh", "tessellate_shape", "DEFAULT_LINEAR_DEFLECTION"]


#: Chord deflection as a fraction of the shape's bounding-box diagonal.
#:
#: 0.1 % gives a visually smooth result on a part a few tens of millimetres across
#: without producing a mesh so dense that interaction becomes sluggish. It is a display
#: setting and has no effect on any computed quantity.
DEFAULT_LINEAR_DEFLECTION = 1.0e-3

#: Angular deflection in radians. Caps the error on tightly curved features such as
#: the inside of a meander turn, where a purely chordal criterion is permissive.
DEFAULT_ANGULAR_DEFLECTION = 0.3


@dataclass
class TriangleMesh:
    """Triangles ready for the viewport.

    ``vertices`` is (N, 3) float64 in model coordinates (mm).
    ``faces`` is (M, 3) int32, zero-based, wound counter-clockwise when seen from
    outside.
    """

    vertices: np.ndarray
    faces: np.ndarray

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.faces.shape[0])

    @property
    def is_empty(self) -> bool:
        return self.vertex_count == 0 or self.triangle_count == 0

    def to_pyvista_faces(self) -> np.ndarray:
        """Flatten to VTK's face format: [3, i, j, k, 3, i, j, k, ...].

        Lives here rather than in the GUI so that the conversion is covered by the
        headless tests. It introduces no PyVista import, so the core/GUI separation
        holds.
        """
        if self.is_empty:
            return np.empty((0,), dtype=np.int64)
        count = self.faces.shape[0]
        padded = np.empty((count, 4), dtype=np.int64)
        padded[:, 0] = 3
        padded[:, 1:] = self.faces
        return padded.ravel()

    @classmethod
    def empty(cls) -> "TriangleMesh":
        return cls(
            vertices=np.empty((0, 3), dtype=np.float64),
            faces=np.empty((0, 3), dtype=np.int32),
        )


def tessellate_shape(
    shape: Any,
    linear_deflection: float | None = None,
    angular_deflection: float = DEFAULT_ANGULAR_DEFLECTION,
    relative_to_size: float | None = None,
) -> TriangleMesh:
    """Triangulate a B-rep shape.

    ``linear_deflection`` is an absolute chord tolerance in mm. If omitted it is
    derived from ``relative_to_size`` (normally the bounding-box diagonal) so that a
    3 mm flexure and a 200 mm hand assembly both come out looking reasonable without
    the caller tuning anything.

    Returns an empty mesh rather than raising when a shape yields no triangles. That
    occurs for shapes with no faces, such as a wire-only import, and is better
    presented as "nothing to draw" than as an error.
    """
    require_kernel()

    if linear_deflection is None:
        size = relative_to_size if relative_to_size and relative_to_size > 0 else 10.0
        linear_deflection = max(size * DEFAULT_LINEAR_DEFLECTION, 1.0e-4)

    # Clear any triangulation left by a previous pass at a different tolerance,
    # otherwise OCCT reuses the stale mesh and silently ignores the new setting.
    try:
        static(occ.BRepTools, "Clean")(shape)
    except Exception:  # pragma: no cover - not fatal, just means a possible stale mesh
        logger.debug("BRepTools.Clean failed; continuing with existing triangulation.")

    occ.BRepMesh_IncrementalMesh(
        shape,
        linear_deflection,
        False,              # isRelative: we have already resolved an absolute value
        angular_deflection,
        True,               # isInParallel
    )

    vertex_blocks: list[np.ndarray] = []
    face_blocks: list[np.ndarray] = []
    offset = 0

    face_enum = occ.TopAbs_ShapeEnum.TopAbs_FACE
    to_face = static(occ.TopoDS, "Face")
    get_triangulation = static(occ.BRep_Tool, "Triangulation")

    explorer = occ.TopExp_Explorer(shape, face_enum)
    while explorer.More():
        face = to_face(explorer.Current())
        location = occ.TopLoc_Location()
        triangulation = get_triangulation(face, location)
        explorer.Next()

        if triangulation is None:
            continue

        node_count = triangulation.NbNodes()
        triangle_count = triangulation.NbTriangles()
        if node_count == 0 or triangle_count == 0:
            continue

        # OCCT stores nodes in the face's local frame; the location carries the
        # placement. Applying it is what puts assembly components where they belong.
        transform = location.Transformation()

        nodes = np.empty((node_count, 3), dtype=np.float64)
        for i in range(1, node_count + 1):          # OCCT indices are 1-based
            point = triangulation.Node(i).Transformed(transform)
            nodes[i - 1] = (point.X(), point.Y(), point.Z())

        # A face flagged REVERSED has its triangles wound the other way round. Left
        # uncorrected, the lighting on those faces comes out inside-out.
        reversed_face = face.Orientation() == occ.TopAbs_Orientation.TopAbs_REVERSED

        tris = np.empty((triangle_count, 3), dtype=np.int32)
        for i in range(1, triangle_count + 1):
            a, b, c = triangulation.Triangle(i).Get()
            if reversed_face:
                a, c = c, a
            tris[i - 1] = (a - 1 + offset, b - 1 + offset, c - 1 + offset)

        vertex_blocks.append(nodes)
        face_blocks.append(tris)
        offset += node_count

    if not vertex_blocks:
        logger.info("Tessellation produced no triangles; the shape has no meshable faces.")
        return TriangleMesh.empty()

    return TriangleMesh(
        vertices=np.vstack(vertex_blocks),
        faces=np.vstack(face_blocks),
    )
