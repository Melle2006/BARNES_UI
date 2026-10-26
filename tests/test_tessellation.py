"""Tessellation tests.

The display mesh is never a source of reported measurements, but it must be correct
enough to look right and to support point picking.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.cad.registry import load_geometry
from barnes_ui.core.cad.tessellate import TriangleMesh, tessellate_shape

from conftest import BOX_VOLUME, requires_kernel


class TestTriangleMesh:
    def test_empty_mesh_reports_itself_as_empty(self) -> None:
        mesh = TriangleMesh.empty()
        assert mesh.is_empty
        assert mesh.vertex_count == 0
        assert mesh.triangle_count == 0

    def test_pyvista_face_format_prefixes_each_triangle_with_three(self) -> None:
        mesh = TriangleMesh(
            vertices=np.zeros((3, 3)),
            faces=np.array([[0, 1, 2]], dtype=np.int32),
        )
        assert mesh.to_pyvista_faces().tolist() == [3, 0, 1, 2]

    def test_pyvista_face_format_length_is_four_per_triangle(self) -> None:
        mesh = TriangleMesh(
            vertices=np.zeros((6, 3)),
            faces=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32),
        )
        assert len(mesh.to_pyvista_faces()) == 8

    def test_empty_mesh_produces_an_empty_face_array(self) -> None:
        assert len(TriangleMesh.empty().to_pyvista_faces()) == 0


@requires_kernel
class TestTessellateShape:
    def test_box_produces_twelve_triangles(self, box_step) -> None:
        """Six quad faces, two triangles each."""
        solid = load_geometry(box_step).solids[0]
        mesh = tessellate_shape(solid.shape, relative_to_size=solid.bounding_box.diagonal)
        assert mesh.triangle_count == 12
        assert mesh.vertex_count == 24

    def test_face_indices_stay_inside_the_vertex_array(self, box_step) -> None:
        """Per-face index offsetting is easy to get wrong and corrupts the display."""
        solid = load_geometry(box_step).solids[0]
        mesh = tessellate_shape(solid.shape, relative_to_size=solid.bounding_box.diagonal)
        assert mesh.faces.min() >= 0
        assert mesh.faces.max() < mesh.vertex_count

    def test_vertices_lie_within_the_bounding_box(self, box_step) -> None:
        solid = load_geometry(box_step).solids[0]
        box = solid.bounding_box
        mesh = tessellate_shape(solid.shape, relative_to_size=box.diagonal)
        tolerance = 1e-6
        assert mesh.vertices[:, 0].min() >= box.xmin - tolerance
        assert mesh.vertices[:, 0].max() <= box.xmax + tolerance
        assert mesh.vertices[:, 2].max() <= box.zmax + tolerance

    def test_mesh_volume_approximates_the_exact_volume(self, box_step) -> None:
        """A box tessellates exactly, so the divergence-theorem volume must match.

        This is a check on winding and indexing, not a measurement: a mesh with
        inconsistent winding gives a volume near zero.
        """
        solid = load_geometry(box_step).solids[0]
        mesh = tessellate_shape(solid.shape, relative_to_size=solid.bounding_box.diagonal)
        a = mesh.vertices[mesh.faces[:, 0]]
        b = mesh.vertices[mesh.faces[:, 1]]
        c = mesh.vertices[mesh.faces[:, 2]]
        signed = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        assert abs(signed.sum()) == pytest.approx(BOX_VOLUME, rel=1e-6)

    def test_finer_tolerance_does_not_reduce_triangle_count(self, box_step) -> None:
        """Planar faces cannot be refined, but the call must still be honoured."""
        solid = load_geometry(box_step).solids[0]
        coarse = tessellate_shape(solid.shape, linear_deflection=1.0)
        fine = tessellate_shape(solid.shape, linear_deflection=0.001)
        assert fine.triangle_count >= coarse.triangle_count
