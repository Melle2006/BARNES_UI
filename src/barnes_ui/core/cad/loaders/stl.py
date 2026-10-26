"""STL import.

STL is supported for visualisation and rough checking. It is **not** suitable for the
analysis this project exists to perform, and the loader is emphatic about that.

What is lost
------------

An STL has no analytic surfaces. A cylindrical fillet in the original model has become
a fan of triangles at whatever chord tolerance the exporter was set to, and that
setting is not recorded in the file. Every curvature, bend radius and arc length
derived from an STL therefore carries an error of unknown size.

That matters more here than it would in most projects, because flexure bending
stiffness scales with the cube of the width. A width wrong by 3 % gives a stiffness
wrong by nearly 10 %, and nothing on screen would show it.

Volume and surface area are also the mesh's, not the part's: a tessellated cylinder is
an inscribed prism and reports slightly less volume than the true shape.

Accordingly, models loaded here are marked ``is_exact = False``, which makes
``is_analysis_ready`` False and keeps them out of the mechanics modules.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ...units import LengthUnit, UnitConfidence
from ..model import (
    BoundingBox,
    CadFormat,
    GeometryModel,
    SolidInfo,
    TopologyCounts,
    WarningSeverity,
)
from ..tessellate import TriangleMesh
from .errors import GeometryLoadError

logger = logging.getLogger(__name__)

__all__ = ["load_stl"]


def load_stl(path: Path) -> GeometryModel:
    """Load an STL file, treating each connected component as a separate body.

    Splitting into connected components matters because STL has no notion of a body:
    a two-part export is just one undifferentiated soup of triangles. Splitting
    recovers the distinction, which is what lets the component tree show something
    meaningful.
    """
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"File not found: {path}")

    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GeometryLoadError(
            "The 'trimesh' package is required to read STL files. "
            "Install it with: pip install trimesh"
        ) from exc

    try:
        # process=True merges coincident vertices. This is required, not cosmetic:
        # the STL format stores every triangle with its own copy of each corner, so
        # without merging no two triangles share a vertex, nothing is connected to
        # anything, and both connected-component splitting and the watertightness
        # test become meaningless -- a 12-triangle box reports as 12 separate bodies.
        # Merging changes the topology only; no vertex moves, so no geometry changes.
        loaded = trimesh.load_mesh(str(path), process=True)
    except Exception as exc:
        raise GeometryLoadError(
            f"The STL file could not be read: {exc}\n\n"
            "The file may be truncated or may not be an STL."
        ) from exc

    # trimesh returns a Scene for multi-object files; flatten it to one mesh.
    if hasattr(loaded, "dump"):
        meshes = [m for m in loaded.dump() if hasattr(m, "faces")]
        if not meshes:
            raise GeometryLoadError("The STL file contains no triangles.")
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = loaded

    if mesh.faces is None or len(mesh.faces) == 0:
        raise GeometryLoadError("The STL file contains no triangles.")

    # split() separates triangles into connected components. only_watertight=False
    # keeps open shells too -- an unwatertight component is exactly the kind of defect
    # the user needs to be told about, so discarding it would be the wrong move.
    try:
        components = mesh.split(only_watertight=False)
        if len(components) == 0:
            components = [mesh]
    except Exception:  # pragma: no cover - splitting is best-effort
        components = [mesh]

    solids: list[SolidInfo] = []
    for index, component in enumerate(components):
        solids.append(_component_to_solid(component, index))

    model = GeometryModel(
        source_path=path,
        source_format=CadFormat.STL,
        unit=LengthUnit.MILLIMETRE,
        # STL has no unit field whatsoever. This is the canonical ASSUMED case.
        unit_confidence=UnitConfidence.ASSUMED,
        solids=solids,
    )

    model.add_warning(
        WarningSeverity.BLOCKING,
        "STL cannot be used for analysis",
        "STL is a tessellated format with no exact surfaces, so curvature, bend "
        "radius and arc length cannot be measured reliably, and the part cannot be "
        "meshed for structural analysis. Export the part as STEP AP214 instead. The "
        "model is shown here for visual checking only.",
    )
    model.add_warning(
        WarningSeverity.CAUTION,
        "STL files declare no units",
        "Millimetres were assumed. An STL authored in inches would be understated by "
        "a factor of 25.4 with nothing in the file to reveal it. Confirm the unit.",
    )

    non_watertight = [s.index for s in solids if "not watertight" in s.validity_detail]
    if non_watertight:
        model.add_warning(
            WarningSeverity.CAUTION,
            "Mesh is not watertight",
            f"Component(s) {', '.join(map(str, non_watertight))} have boundary edges, "
            "so they do not enclose a volume. The reported volume for those is "
            "unreliable.",
        )

    model.loader_notes.append(
        f"{len(mesh.faces)} triangles in {len(components)} connected component(s)."
    )
    return model


def _component_to_solid(component, index: int) -> SolidInfo:
    """Measure one connected mesh component.

    The measurements are the mesh's, not the original part's, and the caller has
    already attached the warnings that say so.
    """
    watertight = bool(getattr(component, "is_watertight", False))

    # trimesh's volume is signed and meaningless for an open mesh.
    if watertight:
        volume = float(abs(component.volume))
        detail = "Watertight mesh. Volume is the tessellation's, not the exact solid's."
    else:
        volume = 0.0
        detail = (
            "Mesh is not watertight, so it encloses no well-defined volume. "
            "Volume reported as zero rather than as a meaningless number."
        )

    area = float(component.area)
    bounds = np.asarray(component.bounds, dtype=float)
    box = BoundingBox(
        float(bounds[0][0]), float(bounds[0][1]), float(bounds[0][2]),
        float(bounds[1][0]), float(bounds[1][1]), float(bounds[1][2]),
    )

    if watertight:
        centre_array = np.asarray(component.center_mass, dtype=float)
    else:
        # Centroid of the vertices: not a centre of mass, but a usable reference point
        # for the viewport, and labelled as such in validity_detail.
        centre_array = np.asarray(component.vertices, dtype=float).mean(axis=0)
    centre = (float(centre_array[0]), float(centre_array[1]), float(centre_array[2]))

    counts = TopologyCounts(
        solids=1 if watertight else 0,
        shells=1,
        faces=int(len(component.faces)),
        edges=int(len(component.edges)) if hasattr(component, "edges") else 0,
        vertices=int(len(component.vertices)),
    )

    solid = SolidInfo(
        index=index,
        name=f"Mesh component {index + 1}",
        volume=volume,
        surface_area=area,
        centre_of_mass=centre,
        bounding_box=box,
        counts=counts,
        is_valid=watertight,
        validity_detail=detail,
        shape=None,  # no exact geometry exists
    )

    # Cache the display mesh now; re-deriving it later would mean keeping the trimesh
    # object alive for no reason.
    solid.triangles = TriangleMesh(
        vertices=np.asarray(component.vertices, dtype=np.float64),
        faces=np.asarray(component.faces, dtype=np.int32),
    )
    return solid
