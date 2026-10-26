"""The 3D viewport.

Wraps ``pyvistaqt.QtInteractor``. Responsibilities: display tessellated solids, let
the user navigate, provide standard views, a section plane, and point picking for
measurement.

Nothing here computes a reported quantity. Measurement picks a point *on the
tessellation*, so the picked coordinate carries the display mesh's approximation
error. For Phase 1 point-to-point measurement that error is far below the chord
tolerance and acceptable; snapping to exact vertices and edges is Phase 2 work and is
noted as such in the UI.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...core.cad.model import GeometryModel, SolidInfo
from ...core.cad.tessellate import TriangleMesh, tessellate_shape

logger = logging.getLogger(__name__)

__all__ = ["Viewport"]


# Distinct colours for successive solids, so that an assembly's components can be told
# apart. Chosen to stay distinguishable in the default lighting and to avoid
# red/green as the primary pair, which is the most common form of colour blindness.
_SOLID_COLOURS = [
    "#4C8FBD", "#E8A33D", "#7FB069", "#B07AA1",
    "#76B7B2", "#D4A5A5", "#8C8C8C", "#9C755F",
]


class Viewport(QWidget):
    """Interactive 3D view of a geometry model."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        from pyvistaqt import QtInteractor  # imported late: pulls in VTK

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter.interactor)

        self._actors: dict[int, object] = {}
        self._meshes: dict[int, TriangleMesh] = {}
        self._model: GeometryModel | None = None
        self._pick_callback: Callable[[tuple[float, float, float]], None] | None = None

        self._configure_scene()

    # -- scene setup -----------------------------------------------------------

    def _configure_scene(self) -> None:
        self.plotter.set_background("#2B2F36", top="#464C55")
        self.plotter.enable_anti_aliasing()
        # A triad in the corner: orientation is the first thing you lose when
        # tumbling a symmetric part.
        self.plotter.add_axes(interactive=False)
        self.plotter.show_grid(color="#5A6069")

    # -- display ---------------------------------------------------------------

    def show_model(self, model: GeometryModel) -> None:
        """Replace the scene with ``model``."""
        self.clear()
        self._model = model

        if model.curves is not None:
            self._show_curves(model)
            return

        box = model.overall_bounding_box
        reference_size = box.diagonal if box else 10.0

        for solid in model.solids:
            try:
                mesh = self._mesh_for(solid, reference_size)
            except Exception as exc:
                logger.warning("Could not tessellate %s: %s", solid.name, exc)
                continue
            if mesh.is_empty:
                continue
            self._add_solid(solid, mesh)

        self.reset_view()

    def _mesh_for(self, solid: SolidInfo, reference_size: float) -> TriangleMesh:
        """Triangles for a solid, from the cache, the loader, or the kernel."""
        if solid.triangles is not None:
            return solid.triangles
        if solid.shape is None:
            return TriangleMesh.empty()
        mesh = tessellate_shape(solid.shape, relative_to_size=reference_size)
        solid.triangles = mesh  # cache: tessellation is the slow part of display
        return mesh

    def _add_solid(self, solid: SolidInfo, mesh: TriangleMesh) -> None:
        import pyvista as pv

        grid = pv.PolyData(mesh.vertices, mesh.to_pyvista_faces())
        colour = _SOLID_COLOURS[solid.index % len(_SOLID_COLOURS)]

        actor = self.plotter.add_mesh(
            grid,
            color=colour,
            smooth_shading=True,
            specular=0.3,
            specular_power=15,
            name=f"solid_{solid.index}",
        )
        self._actors[solid.index] = actor
        self._meshes[solid.index] = mesh

    def _show_curves(self, model: GeometryModel) -> None:
        """Draw DXF polylines."""
        import pyvista as pv

        for index, points in enumerate(model.curves.polylines):
            if len(points) < 2:
                continue
            # VTK's polyline cell format: [n, i0, i1, ... i(n-1)]
            cells = np.hstack([[len(points)], np.arange(len(points))])
            line = pv.PolyData(points)
            line.lines = cells
            self.plotter.add_mesh(line, color="#E8A33D", line_width=2,
                                  name=f"curve_{index}")
        self.reset_view()

    def clear(self) -> None:
        self.plotter.clear()
        self._actors.clear()
        self._meshes.clear()
        self._model = None
        self._configure_scene()

    def set_solid_visible(self, index: int, visible: bool) -> None:
        actor = self._actors.get(index)
        if actor is not None:
            actor.SetVisibility(bool(visible))
            self.plotter.render()

    # -- navigation ------------------------------------------------------------

    def reset_view(self) -> None:
        self.plotter.reset_camera()
        self.plotter.view_isometric()
        self.plotter.render()

    def view_iso(self) -> None:
        self.plotter.view_isometric()
        self.plotter.render()

    def view_front(self) -> None:
        self.plotter.view_xz()
        self.plotter.render()

    def view_top(self) -> None:
        self.plotter.view_xy()
        self.plotter.render()

    def view_right(self) -> None:
        self.plotter.view_yz()
        self.plotter.render()

    def fit(self) -> None:
        self.plotter.reset_camera()
        self.plotter.render()

    # -- section plane ---------------------------------------------------------

    def enable_section(self, enabled: bool) -> None:
        """Toggle an interactive clipping plane.

        Rebuilds the scene from the cached triangle meshes, because PyVista's clip
        widget wraps the meshes rather than the existing actors.
        """
        import pyvista as pv

        if not self._model:
            return

        self.plotter.clear()
        self._configure_scene()
        self._actors.clear()

        for index, mesh in self._meshes.items():
            grid = pv.PolyData(mesh.vertices, mesh.to_pyvista_faces())
            colour = _SOLID_COLOURS[index % len(_SOLID_COLOURS)]
            if enabled:
                self.plotter.add_mesh_clip_plane(
                    grid, color=colour, smooth_shading=True,
                    name=f"solid_{index}", normal="x", invert=False,
                )
            else:
                actor = self.plotter.add_mesh(
                    grid, color=colour, smooth_shading=True,
                    specular=0.3, specular_power=15, name=f"solid_{index}",
                )
                self._actors[index] = actor

        if not enabled:
            self.plotter.clear_plane_widgets()
        self.plotter.render()

    # -- measurement -----------------------------------------------------------

    def start_point_picking(
        self, callback: Callable[[tuple[float, float, float]], None]
    ) -> None:
        """Begin picking points on the surface.

        The picked point lies on the display tessellation, so it carries the chord
        tolerance of the mesh. That is well below the precision needed for the
        overall-dimension checks Phase 1 targets. Snapping to exact vertices and
        edges needs the kernel's topology and is Phase 2 work.
        """
        self._pick_callback = callback
        self.plotter.enable_surface_point_picking(
            callback=self._on_point_picked,
            show_message=False,
            show_point=True,
            point_size=12,
            color="#FF6B6B",
        )

    def stop_point_picking(self) -> None:
        self._pick_callback = None
        try:
            self.plotter.disable_picking()
        except Exception:  # pragma: no cover - depends on PyVista version
            logger.debug("disable_picking() unavailable in this PyVista build.")

    def _on_point_picked(self, point, *_args) -> None:
        if self._pick_callback is None or point is None:
            return
        coords = np.asarray(point, dtype=float).ravel()
        if coords.size < 3:
            return
        self._pick_callback((float(coords[0]), float(coords[1]), float(coords[2])))

    def draw_measurement_line(
        self, start: tuple[float, float, float], end: tuple[float, float, float]
    ) -> None:
        import pyvista as pv

        self.plotter.add_mesh(
            pv.Line(start, end), color="#FF6B6B", line_width=3, name="measurement_line"
        )
        self.plotter.render()

    def clear_measurement(self) -> None:
        for name in ("measurement_line",):
            try:
                self.plotter.remove_actor(name)
            except Exception:  # pragma: no cover
                pass
        self.plotter.render()

    # -- lifecycle -------------------------------------------------------------

    def close_viewport(self) -> None:
        """Release the VTK render window.

        Must be called before the application exits. A QtInteractor left open at
        shutdown reliably produces a crash or a hang on Windows as VTK and Qt tear
        down in an unfortunate order.
        """
        try:
            self.plotter.close()
        except Exception:  # pragma: no cover
            logger.debug("Viewport close failed; continuing shutdown.")
