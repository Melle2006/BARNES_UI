"""Cross-section extraction from a solid.

Cuts a solid with a plane and measures the resulting face or faces: area, centroid,
and the second moments of area that a beam model needs.

Why the cutting direction matters
---------------------------------

A section must be taken **perpendicular to the local centreline tangent**, not
perpendicular to a convenient global axis. Cutting an inclined member with an
axis-normal plane produces an oblique slice whose area and depth are inflated by
1/cos(theta), where theta is the angle between the tangent and the cutting plane's
normal.

This is not a small effect and it was measured on the real A3 twin-strap part: cutting
perpendicular to global Y gave an apparent thickness of 1.000 mm at the arch apex,
where the strap is horizontal, rising to 1.052 mm near the collars, where it is
inclined by about 17 degrees. Since bending stiffness scales with the cube of depth,
accepting the oblique value would overstate local stiffness by around 16 per cent at
the ends -- exactly where a clamped arch carries its highest moment.

:func:`extract_centerline` in the sibling module therefore runs two passes: axis-normal
cuts to locate an approximate centreline, then tangent-normal cuts along it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..cad._occ import occ, require_kernel, static

logger = logging.getLogger(__name__)

__all__ = ["CrossSection", "section_solid", "SectionError"]


class SectionError(RuntimeError):
    """A sectioning operation failed or produced nothing usable."""


@dataclass(frozen=True)
class CrossSection:
    """One closed region of a planar cut through a solid.

    All quantities are in millimetres and derived units, measured from the exact
    B-rep surfaces rather than from a tessellation.

    The second moments are reported about axes through the section's own centroid.
    ``i_bending`` is the one a planar beam model uses: the second moment about the
    in-plane axis parallel to the bending axis, which for a flexure bending at a finger
    joint is the joint axis.
    """

    area: float
    centroid: tuple[float, float, float]
    #: Extent along the section plane's local U direction, millimetres.
    width_u: float
    #: Extent along the section plane's local V direction, millimetres.
    width_v: float
    #: Second moment of area about the centroidal axis parallel to U, mm^4.
    i_uu: float
    #: Second moment of area about the centroidal axis parallel to V, mm^4.
    i_vv: float
    #: Plane normal the cut was taken with, as a unit vector.
    normal: tuple[float, float, float]
    #: Local U axis of the cutting plane, as a unit vector.
    u_axis: tuple[float, float, float]
    #: Local V axis of the cutting plane, as a unit vector.
    v_axis: tuple[float, float, float]

    @property
    def i_bending(self) -> float:
        """Second moment for bending about the U axis.

        U is chosen by the caller to be the bending axis -- for a finger flexure, the
        joint axis -- so this is the quantity that enters EI in the beam model.
        """
        return self.i_uu

    @property
    def equivalent_rectangle(self) -> tuple[float, float]:
        """Width and depth of a rectangle with the same area and i_uu.

        Useful for sanity-checking against a hand calculation and for reporting a
        section that is nearly rectangular in familiar terms. For a genuinely
        rectangular section this returns its actual dimensions.

        Derivation: for a rectangle of width b (along U) and depth h (along V),
        A = b*h and I_uu = b*h^3/12, so h = sqrt(12*I/A) and b = A/h.
        """
        if self.area <= 0.0:
            return (0.0, 0.0)
        depth = math.sqrt(12.0 * self.i_uu / self.area)
        width = self.area / depth if depth > 0 else 0.0
        return (width, depth)

    @property
    def rectangularity(self) -> float:
        """How close the section is to a filled rectangle, in [0, 1].

        Area divided by the area of its bounding rectangle in the cutting plane. 1.0 is
        a perfect rectangle; a value well below 1 means the equivalent-rectangle figures
        should not be read as real dimensions.
        """
        bounding = self.width_u * self.width_v
        return self.area / bounding if bounding > 0 else 0.0


def section_solid(
    shape: Any,
    origin: Sequence[float],
    normal: Sequence[float],
    u_hint: Sequence[float] | None = None,
    min_area: float = 1.0e-9,
) -> list[CrossSection]:
    """Cut ``shape`` with a plane and measure each closed region.

    Parameters
    ----------
    shape:
        An OpenCASCADE solid.
    origin:
        A point on the cutting plane, in model coordinates.
    normal:
        The plane normal. For a beam section this is the local centreline tangent.
    u_hint:
        Preferred direction for the plane's local U axis, which fixes which of the two
        in-plane second moments is ``i_uu``. For a finger flexure, pass the joint axis,
        so that ``i_bending`` is the one entering EI. The hint is projected into the
        plane and normalised; if it is parallel to the normal, an arbitrary
        perpendicular is chosen and a warning is logged, because silently picking a
        different axis would swap I_uu and I_vv without telling anyone.
    min_area:
        Regions smaller than this are discarded as numerical debris from the boolean.

    Returns
    -------
    One :class:`CrossSection` per closed region, ordered by descending area. A flexure
    with two parallel straps returns two regions, which is how the straps are separated.

    Raises
    ------
    SectionError
        If the boolean operation fails outright. An empty list is returned rather than
        raised when the plane simply misses the solid, since asking for a section
        beyond the end of a member is a normal thing for a sweep to do.
    """
    require_kernel()

    n = _unit(np.asarray(normal, dtype=float))
    o = np.asarray(origin, dtype=float)

    u = _resolve_u_axis(n, u_hint)
    v = np.cross(n, u)

    plane = occ.gp_Pln(
        occ.gp_Ax3(
            occ.gp_Pnt(float(o[0]), float(o[1]), float(o[2])),
            occ.gp_Dir(float(n[0]), float(n[1]), float(n[2])),
            occ.gp_Dir(float(u[0]), float(u[1]), float(u[2])),
        )
    )

    try:
        algo = occ.BRepAlgoAPI_Section(shape, plane, False)
        algo.ComputePCurveOn1(True)
        algo.Approximation(True)
        algo.Build()
    except Exception as exc:  # pragma: no cover - kernel failure
        raise SectionError(f"Sectioning failed at {tuple(o)}: {exc}") from exc

    if not algo.IsDone():
        raise SectionError(f"Sectioning did not complete at {tuple(o)}.")

    edges = occ.HSequence_TopoDS_Shape()
    explorer = occ.TopExp_Explorer(algo.Shape(), occ.TopAbs_ShapeEnum.TopAbs_EDGE)
    while explorer.More():
        edges.Append(explorer.Current())
        explorer.Next()

    if edges.Length() == 0:
        return []  # the plane misses the solid; not an error

    wires = static(occ.ShapeAnalysis_FreeBounds, "ConnectEdgesToWires")(
        edges, 1.0e-6, False
    )

    to_wire = static(occ.TopoDS, "Wire")
    sections: list[CrossSection] = []

    for index in range(1, wires.Length() + 1):
        try:
            wire = to_wire(wires.Value(index))
            maker = occ.BRepBuilderAPI_MakeFace(plane, wire)
            if not maker.IsDone():
                continue
            face = maker.Face()
        except Exception as exc:
            logger.debug("Could not build a face from section wire %d: %s", index, exc)
            continue

        props = occ.GProp_GProps()
        static(occ.BRepGProp, "SurfaceProperties")(face, props)
        area = props.Mass()
        if area < min_area:
            continue

        com = props.CentreOfMass()
        centroid = np.array([com.X(), com.Y(), com.Z()])

        i_uu, i_vv = _planar_second_moments(props, u, v)
        width_u, width_v = _planar_extents(face, centroid, u, v)

        sections.append(
            CrossSection(
                area=area,
                centroid=(float(centroid[0]), float(centroid[1]), float(centroid[2])),
                width_u=width_u,
                width_v=width_v,
                i_uu=i_uu,
                i_vv=i_vv,
                normal=(float(n[0]), float(n[1]), float(n[2])),
                u_axis=(float(u[0]), float(u[1]), float(u[2])),
                v_axis=(float(v[0]), float(v[1]), float(v[2])),
            )
        )

    sections.sort(key=lambda s: -s.area)
    return sections


def _planar_second_moments(
    props: Any, u: np.ndarray, v: np.ndarray
) -> tuple[float, float]:
    """Second moments of area about centroidal axes along ``u`` and ``v``.

    OpenCASCADE's GProp returns a full 3x3 inertia tensor about the centre of mass,
    computed for unit surface density, so its entries are second moments of area in
    mm^4. The tensor is in global axes, so it is rotated into the section's own frame.

    For a planar region, the moment of inertia about an in-plane axis d is d^T J d,
    where J is that tensor. Taking the U axis gives the resistance to bending that
    puts the neutral axis along U -- which is the quantity beam theory calls I for
    bending about U.
    """
    matrix = props.MatrixOfInertia()
    tensor = np.array(
        [[matrix.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)], dtype=float
    )
    i_uu = float(u @ tensor @ u)
    i_vv = float(v @ tensor @ v)
    return i_uu, i_vv


def _planar_extents(
    face: Any, centroid: np.ndarray, u: np.ndarray, v: np.ndarray
) -> tuple[float, float]:
    """Extent of a face along the in-plane U and V directions.

    Measured from the face's vertices. A global axis-aligned bounding box would be
    wrong here: the section plane is generally oblique to the global axes, so an
    axis-aligned box of an inclined rectangle is larger than the rectangle.
    """
    points: list[np.ndarray] = []
    explorer = occ.TopExp_Explorer(face, occ.TopAbs_ShapeEnum.TopAbs_VERTEX)
    to_vertex = static(occ.TopoDS, "Vertex")
    point_of = static(occ.BRep_Tool, "Pnt")
    while explorer.More():
        pnt = point_of(to_vertex(explorer.Current()))
        points.append(np.array([pnt.X(), pnt.Y(), pnt.Z()]))
        explorer.Next()

    if not points:
        return (0.0, 0.0)

    relative = np.vstack(points) - centroid
    along_u = relative @ u
    along_v = relative @ v
    return (float(along_u.max() - along_u.min()), float(along_v.max() - along_v.min()))


def _resolve_u_axis(normal: np.ndarray, hint: Sequence[float] | None) -> np.ndarray:
    """Choose an in-plane U axis, honouring the caller's hint where possible."""
    if hint is not None:
        candidate = np.asarray(hint, dtype=float)
        projected = candidate - np.dot(candidate, normal) * normal
        if np.linalg.norm(projected) > 1.0e-8:
            return _unit(projected)
        logger.warning(
            "The requested U axis %s is parallel to the section normal %s, so an "
            "arbitrary in-plane axis was used instead. I_uu and I_vv will not mean "
            "what the caller expects.",
            tuple(candidate), tuple(normal),
        )

    # Pick whichever global axis is least aligned with the normal, so the cross
    # product is well conditioned.
    fallback = np.zeros(3)
    fallback[int(np.argmin(np.abs(normal)))] = 1.0
    return _unit(np.cross(normal, fallback))


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm < 1.0e-12:
        raise ValueError("Cannot normalise a zero-length vector.")
    return vector / norm
