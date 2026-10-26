"""Measurement of imported B-rep geometry.

All quantities are read from the exact analytic geometry via OpenCASCADE, not from a
tessellation, so a cylinder's volume is integrated rather than approximated by
triangles. These are the values that carry the ``GEOMETRIC_MEASUREMENT`` provenance
tag.

Units: OpenCASCADE's STEP and IGES readers convert incoming geometry to millimetres, so
everything here is in mm, mm^2 and mm^3 -- the project's canonical system.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ..units import LengthUnit
from ._occ import occ, require_kernel, static
from .model import BoundingBox, SolidInfo, TopologyCounts

logger = logging.getLogger(__name__)

__all__ = [
    "iter_subshapes",
    "split_into_solids",
    "topology_counts",
    "volume_properties",
    "surface_area",
    "bounding_box",
    "check_validity",
    "inspect_solid",
    "inspect_shape",
]


def iter_subshapes(shape: Any, shape_type: Any) -> Iterator[Any]:
    """Yield every sub-shape of the given topological type.

    Wraps the explorer idiom, which is otherwise a five-line while loop repeated at
    every call site.
    """
    explorer = occ.TopExp_Explorer(shape, shape_type)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def split_into_solids(shape: Any) -> list[Any]:
    """Break a shape into its constituent solids.

    A STEP file commonly transfers as a single compound containing several solids --
    an assembly, or a part modelled as disjoint bodies. Each is measured separately,
    because reporting one combined volume for an assembly would be meaningless.

    Falls back to shells when no solid is present. That happens when an export produced
    surfaces that never got sewn into a closed volume, which is itself worth knowing:
    the caller raises a warning on it, because a surface model has no volume and cannot
    be meshed for structural analysis.
    """
    require_kernel()
    solids = list(iter_subshapes(shape, occ.TopAbs_ShapeEnum.TopAbs_SOLID))
    if solids:
        return solids
    shells = list(iter_subshapes(shape, occ.TopAbs_ShapeEnum.TopAbs_SHELL))
    if shells:
        logger.warning(
            "No solids found; falling back to %d shell(s). The import is a surface "
            "model, not a volume.",
            len(shells),
        )
        return shells
    # Nothing recognisable: hand back the shape itself so the caller can still
    # display it and report what it found.
    return [shape] if not shape.IsNull() else []


def topology_counts(shape: Any) -> TopologyCounts:
    """Count topological entities in a shape."""
    require_kernel()
    enum = occ.TopAbs_ShapeEnum
    return TopologyCounts(
        solids=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_SOLID)),
        shells=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_SHELL)),
        faces=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_FACE)),
        wires=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_WIRE)),
        edges=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_EDGE)),
        vertices=sum(1 for _ in iter_subshapes(shape, enum.TopAbs_VERTEX)),
    )


def volume_properties(shape: Any) -> tuple[float, tuple[float, float, float], tuple[tuple[float, ...], ...]]:
    """Volume, centre of mass and inertia tensor of a solid.

    OpenCASCADE's ``GProp`` routines compute "mass" with unit density, so the returned
    mass *is* the volume in mm^3. The inertia tensor is likewise per unit density and
    is taken about the centre of mass.

    No density is applied and no mass is returned. Density is a material property, and
    inventing one here to produce a mass would be exactly the kind of quiet assumption
    this project avoids.
    """
    require_kernel()
    props = occ.GProp_GProps()
    static(occ.BRepGProp, "VolumeProperties")(shape, props)
    com = props.CentreOfMass()
    matrix = props.MatrixOfInertia()
    inertia = tuple(
        tuple(matrix.Value(row, col) for col in (1, 2, 3)) for row in (1, 2, 3)
    )
    return props.Mass(), (com.X(), com.Y(), com.Z()), inertia


def surface_area(shape: Any) -> float:
    """Total area of all faces, in mm^2."""
    require_kernel()
    props = occ.GProp_GProps()
    static(occ.BRepGProp, "SurfaceProperties")(shape, props)
    return props.Mass()


def bounding_box(shape: Any, optimal: bool = True) -> BoundingBox:
    """Axis-aligned bounding box in the model's coordinate system.

    ``optimal=True`` uses ``BRepBndLib.AddOptimal``, which computes a tight box from the
    exact surfaces. The default ``Add`` inflates the box to safely enclose the
    tessellation and can overstate a curved part's extent by a noticeable margin -- not
    acceptable when the number is being compared against a SolidWorks mass-properties
    readout to 0.1 %.

    ``useShapeTolerance`` is passed as False deliberately. Setting it True pads every
    face by its modelling tolerance, which turned a 10 mm box into 10.0000002 mm in
    testing. That is harmless for a clash check and wrong for a reported dimension,
    and this function's output is a reported dimension.

    The tight computation is slower. For a single flexure that is irrelevant; for a
    large assembly the caller can ask for the fast version.
    """
    require_kernel()
    box = occ.Bnd_Box()
    if optimal:
        static(occ.BRepBndLib, "AddOptimal")(shape, box, True, False)
    else:
        static(occ.BRepBndLib, "Add")(shape, box, True)
    if box.IsVoid():
        raise ValueError("Bounding box is empty; the shape contains no geometry.")
    lo, hi = box.CornerMin(), box.CornerMax()
    return BoundingBox(lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())


def check_validity(shape: Any) -> tuple[bool, str]:
    """Run OpenCASCADE's topological consistency check.

    Returns ``(is_valid, detail)``. The analyser verifies that the boundary
    representation is self-consistent: faces bounded by closed wires, edges shared
    correctly between faces, no self-intersecting wires, orientations coherent.

    What it does *not* tell you is whether the geometry is sensible for analysis. A
    valid solid can still be a sliver too thin to mesh. Validity is necessary, not
    sufficient, and the UI presents it that way.
    """
    require_kernel()
    try:
        analyzer = occ.BRepCheck_Analyzer(shape)
        valid = bool(analyzer.IsValid())
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Validity check could not be completed: {exc}"
    if valid:
        return True, "Topology is self-consistent (BRepCheck_Analyzer)."
    return False, (
        "BRepCheck_Analyzer reports invalid topology. Common causes are an export "
        "tolerance mismatch, self-intersecting faces, or unsewn surfaces. Try "
        "re-exporting from SolidWorks as STEP AP214 with a tighter tolerance."
    )


def inspect_solid(shape: Any, index: int, name: str = "") -> SolidInfo:
    """Measure one solid and package the results.

    Measurement failures are caught per-quantity rather than aborting the whole import.
    A solid with a degenerate face may still yield a usable bounding box and topology
    count, and showing the user what *could* be read is more helpful than refusing to
    show anything. Anything that could not be measured comes back as zero with the
    reason recorded in ``validity_detail``.
    """
    require_kernel()
    failures: list[str] = []

    try:
        volume, centre, inertia = volume_properties(shape)
    except Exception as exc:
        logger.warning("Volume computation failed for solid %d: %s", index, exc)
        volume, centre, inertia = 0.0, (0.0, 0.0, 0.0), None
        failures.append(f"volume: {exc}")

    try:
        area = surface_area(shape)
    except Exception as exc:
        logger.warning("Surface area computation failed for solid %d: %s", index, exc)
        area = 0.0
        failures.append(f"surface area: {exc}")

    try:
        box = bounding_box(shape)
    except Exception as exc:
        logger.warning("Bounding box failed for solid %d: %s", index, exc)
        box = BoundingBox(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        failures.append(f"bounding box: {exc}")

    is_valid, detail = check_validity(shape)
    if failures:
        is_valid = False
        detail = f"{detail} Measurement problems: {'; '.join(failures)}"

    # A negative volume means the solid's faces are inward-oriented, which happens with
    # some exports. The magnitude is still correct, so report it and flag the cause
    # rather than showing the user a negative volume.
    if volume < 0:
        logger.info("Solid %d had negative volume; orientation is inverted.", index)
        volume = abs(volume)
        detail = f"{detail} Face orientation is inverted (volume was negative)."

    return SolidInfo(
        index=index,
        name=name or f"Solid {index + 1}",
        volume=volume,
        surface_area=area,
        centre_of_mass=centre,
        bounding_box=box,
        counts=topology_counts(shape),
        is_valid=is_valid,
        validity_detail=detail,
        inertia_tensor=inertia,
        shape=shape,
    )


def inspect_shape(shape: Any, names: list[str] | None = None) -> list[SolidInfo]:
    """Split a shape into solids and measure each one.

    ``names`` optionally supplies component names recovered from the file, positionally
    matched to the solids. Where a name is missing a generic one is generated, because
    an unnamed row in the component tree is worse than a numbered one.
    """
    require_kernel()
    solids = split_into_solids(shape)
    out: list[SolidInfo] = []
    for index, solid in enumerate(solids):
        name = ""
        if names and index < len(names):
            name = names[index] or ""
        out.append(inspect_solid(solid, index, name))
    return out


def unit_from_occ_import() -> LengthUnit:
    """The unit that B-rep geometry is in after OpenCASCADE has read it.

    Always millimetres. OCCT's STEP and IGES readers apply the conversion from the
    file's declared unit as they read, controlled by the ``xstep.cascade.unit``
    parameter which the loaders set explicitly to ``MM``.

    This exists as a named function rather than a bare constant so that the reason is
    attached to the fact at every call site -- the alternative is someone later
    converting a second time from the file's declared unit and scaling the model by
    25.4.
    """
    return LengthUnit.MILLIMETRE
