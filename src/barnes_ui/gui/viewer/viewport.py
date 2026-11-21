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
        self._miss_callback: Callable[[], None] | None = None
        # Incremented on every start_point_picking. Handed to the caller so that a
        # point arriving from a session that has since been torn down can be told
        # apart from a real pick -- VTK observers outlive the code that added them.
        self._pick_session = 0
        self._picking_active = False

        self._configure_scene()

    # -- scene setup -----------------------------------------------------------

    def _configure_scene(self) -> None:
        self.plotter.set_background("#2B2F36", top="#464C55")
        self.plotter.enable_anti_aliasing()
        # A triad in the corner: orientation is the first thing you lose when
        # tumbling a symmetric part.
        self.plotter.add_axes(interactive=False)
        grid = self.plotter.show_grid(color="#5A6069")
        # The bounds grid must never be a pick target. A click that lands on it
        # would otherwise report a coordinate out in empty space as though it were
        # on the part.
        try:
            grid.SetPickable(False)
        except AttributeError:  # pragma: no cover - depends on the VTK actor type
            logger.debug("Bounds grid actor does not support SetPickable.")

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
        """Empty the scene.

        Picking is torn down first, deliberately. ``Plotter.clear`` removes the
        actors and the on-screen picking instruction but leaves PyVista's picking
        observers installed and its internal ``_picker_in_use`` flag set, so a
        viewport cleared mid-pick is left armed against geometry that no longer
        exists -- and the next ``enable_*_picking`` raises ``PyVistaPickingError``
        rather than re-arming.
        """
        self.stop_point_picking()
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

        # Same reasoning as in clear(): the scene is about to be rebuilt, so any
        # live picking session is pointing at actors that are going away.
        self.stop_point_picking()
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

    # -- point picking ---------------------------------------------------------
    #
    # Everything below turns mouse events into coordinates and draws what was
    # captured. It decides nothing about what a pair of points means; that is
    # viewer/selection.py's job.

    #: Names of the actors this class owns for selection feedback. Named so that
    #: they can be replaced and removed individually -- PyVista's own picked-point
    #: representation uses one name for every pick, so each new point replaces the
    #: marker for the previous one and a two-point selection is never both visible.
    _MARKER_NAMES = ("selection_point_1", "selection_point_2")
    _LINE_NAME = "selection_line"
    _INSTRUCTION_NAME = "selection_instruction"

    def start_point_picking(
        self,
        callback: Callable[[tuple[float, float, float]], None],
        *,
        on_miss: Callable[[], None] | None = None,
        instruction: str | None = None,
    ) -> int:
        """Arm picking on the surface of the displayed solids.

        Returns a session token. Hand it back to the selection controller with each
        point so that a callback from a replaced session is discarded.

        The picked point lies on the display tessellation, so it carries the chord
        tolerance of the mesh. That is well below the precision needed for the
        overall-dimension checks Phase 1 targets. Snapping to exact vertices and
        edges needs the kernel's topology and is still not implemented -- the panel
        says so, and that warning stays until it is.

        Three of the arguments here are the fix for the original defect and are
        worth stating:

        ``left_clicking=True``
            PyVista binds picking to the **right** button and the ``P`` key by
            default (``picking.py``: ``'Left-click' if left_clicking else
            'Right-click'``). The panel told the user to click, the left button did
            nothing, and the on-screen hint that would have revealed it was
            suppressed by ``show_message=False``.

        ``pickable_window=True``
            Not because empty space should be pickable -- it should not -- but
            because PyVista returns early on a miss *before* invoking the callback,
            so with the default there is no way to learn that a click happened at
            all. The miss is detected here instead, from the picker's actor, and
            reported through ``on_miss``.

        ``show_point=False``
            Markers are drawn by this class, one actor per point, so that both
            points of a pair stay visible.
        """
        # Re-arming over a live session raises in PyVista, so tear down first. This
        # also makes the call idempotent, which matters because the panel's toggle
        # and a model replacement can both reach it.
        self.stop_point_picking()

        self._pick_callback = callback
        self._miss_callback = on_miss
        self._pick_session += 1
        self._picking_active = True

        self.plotter.enable_surface_point_picking(
            callback=self._on_point_picked,
            use_picker=True,
            pickable_window=True,
            clear_on_no_selection=False,
            show_point=False,
            show_message=False,
            left_clicking=True,
            picker="cell",
            tolerance=0.01,
        )
        if instruction:
            self.set_picking_instruction(instruction)
        return self._pick_session

    def stop_point_picking(self) -> None:
        """Disarm picking and remove the on-screen instruction.

        Leaves the markers and the line alone: stopping the tool is not the same as
        discarding the result, and the panel decides which of those happened. Call
        ``clear_selection_graphics`` for the other one.
        """
        self._pick_callback = None
        self._miss_callback = None
        self._picking_active = False
        try:
            self.plotter.disable_picking()
        except Exception:  # pragma: no cover - depends on PyVista version
            logger.debug("disable_picking() unavailable in this PyVista build.")
        self._remove_actors((self._INSTRUCTION_NAME,))

    @property
    def is_picking(self) -> bool:
        return self._picking_active

    @property
    def pick_session(self) -> int:
        return self._pick_session

    def _on_point_picked(self, point, picker=None) -> None:
        """VTK's pick callback. Decides hit or miss, then hands over coordinates."""
        if not self._picking_active:
            return

        # A pick with no actor behind it is a click into the background. It must not
        # become a coordinate: ``GetPickPosition`` still returns a point on the
        # focal plane, which looks like a perfectly ordinary measurement.
        if picker is not None:
            try:
                if picker.GetActor() is None:
                    if self._miss_callback is not None:
                        self._miss_callback()
                    return
            except AttributeError:  # pragma: no cover - picker without GetActor
                logger.debug("Picker has no GetActor; treating the pick as a hit.")

        if self._pick_callback is None or point is None:
            return
        coords = np.asarray(point, dtype=float).ravel()
        if coords.size < 3:
            return
        self._pick_callback((float(coords[0]), float(coords[1]), float(coords[2])))

    # -- selection feedback ----------------------------------------------------

    def set_picking_instruction(self, text: str) -> None:
        """Put the current instruction in the viewport itself.

        In the viewport and not only in the panel, because the eyes are on the model
        while picking. One named actor, replaced on each update.
        """
        self.plotter.add_text(
            text,
            position="lower_left",
            font_size=9,
            color="#D8DEE6",
            name=self._INSTRUCTION_NAME,
        )
        self.plotter.render()

    def mark_point(self, index: int, point: tuple[float, float, float]) -> None:
        """Draw the marker for picked point ``index`` (0 or 1)."""
        import pyvista as pv

        if not 0 <= index < len(self._MARKER_NAMES):
            raise ValueError(f"A two-point selection has no point {index}.")
        self.plotter.add_mesh(
            pv.PolyData(np.asarray([point], dtype=float)),
            color="#FF6B6B",
            style="points",  # explicit: a single-point dataset must not be surfaced
            point_size=14,
            render_points_as_spheres=True,
            name=self._MARKER_NAMES[index],
            pickable=False,  # a marker must never become the next pick target
            reset_camera=False,
        )
        self.plotter.render()

    def draw_measurement_line(
        self, start: tuple[float, float, float], end: tuple[float, float, float]
    ) -> None:
        import pyvista as pv

        self.plotter.add_mesh(
            pv.Line(start, end),
            color="#FF6B6B",
            line_width=3,
            name=self._LINE_NAME,
            pickable=False,
            reset_camera=False,
        )
        self.plotter.render()

    def draw_axis_preview(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        length: float | None = None,
    ) -> None:
        """Draw a candidate joint axis as a line through ``origin``.

        Extended well past the two picked points on purpose. The question a person
        has to answer before confirming an axis is whether the line passes through
        where the joint actually rotates, and a segment that stops at the picks is
        too short to judge that against the part.
        """
        import pyvista as pv

        if length is None:
            box = self._model.overall_bounding_box if self._model else None
            length = box.diagonal if box else 10.0
        half = 0.5 * float(length)
        axis = np.asarray(direction, dtype=float)
        norm = float(np.linalg.norm(axis))
        if norm <= 0.0:
            raise ValueError("An axis preview needs a non-zero direction.")
        axis = axis / norm
        centre = np.asarray(origin, dtype=float)

        self.plotter.add_mesh(
            pv.Line(centre - half * axis, centre + half * axis),
            color="#E8A33D",
            line_width=3,
            name=self._LINE_NAME,
            pickable=False,
            reset_camera=False,
        )
        self.plotter.render()

    def clear_selection_graphics(self) -> None:
        """Remove every marker and line this class drew for a selection."""
        self._remove_actors((*self._MARKER_NAMES, self._LINE_NAME))
        self.plotter.render()

    # Kept under its original name: the measurement panel is not the only caller
    # and "clear the measurement" is still what it means there.
    clear_measurement = clear_selection_graphics

    def _remove_actors(self, names) -> None:
        for name in names:
            try:
                self.plotter.remove_actor(name, render=False)
            except Exception:  # pragma: no cover - absent actor, nothing to undo
                logger.debug("Could not remove actor %s.", name)

    # -- lifecycle -------------------------------------------------------------

    def close_viewport(self) -> None:
        """Release the VTK render window.

        Must be called before the application exits. A QtInteractor left open at
        shutdown reliably produces a crash or a hang on Windows as VTK and Qt tear
        down in an unfortunate order.

        Picking is disarmed first so that no observer is left holding a reference
        into a half-destroyed render window.
        """
        try:
            self.stop_point_picking()
        except Exception:  # pragma: no cover
            logger.debug("Disarming picking at shutdown raised; continuing.")
        try:
            self.plotter.close()
        except Exception:  # pragma: no cover
            logger.debug("Viewport close failed; continuing shutdown.")
