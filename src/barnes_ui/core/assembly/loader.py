"""STEP assembly import, preserving component structure and placement.

The ordinary ``STEPControl_Reader`` used by ``cad.loaders.step`` returns a single shape
with every placement baked in. That is correct for a part and lossy for an assembly:
component names, the tree and the individual transforms are gone. This module uses the
XCAF reader (``STEPCAFControl_Reader``), which populates an OCAF document with the
product structure that an assembly STEP actually contains.

What STEP does and does not carry
---------------------------------

It carries: the component tree, each component's name, and each component's placement
relative to its parent.

It does not carry: mates, constraints, degrees of freedom, or any statement of which
component moves relative to which. A revolute joint between two phalanges looks
identical in the file to two parts that happen to be near each other. Everything
kinematic is therefore a user decision -- see :mod:`barnes_ui.core.assembly.joint` and
risk R4.

Units
-----

Same convention as the part loader: OpenCASCADE converts geometry to millimetres as it
reads, so ``Assembly.unit`` is always millimetres and ``declared_unit`` records what the
file said, for information only. Applying the declared unit as a scale factor after
import would apply it twice.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ..cad._occ import occ, require_kernel, static
from ..cad.inspect import bounding_box, volume_properties
from ..cad.loaders.errors import GeometryLoadError
from ..cad.loaders.step import parse_declared_unit
from ..units import LengthUnit, UnitConfidence
from .model import Assembly, Component, Placement

logger = logging.getLogger(__name__)

__all__ = ["load_step_assembly"]


def load_step_assembly(path: Path | str) -> Assembly:
    """Read a STEP assembly into an :class:`Assembly`.

    A STEP file containing a single part loads perfectly well: the result is an
    assembly with one root component and no children. That is deliberate, so callers
    do not need two code paths.
    """
    require_kernel()
    path = Path(path)
    if not path.is_file():
        raise GeometryLoadError(f"No such file: {path}")

    document = occ.TDocStd_Document(occ.TCollection_ExtendedString("barnes"))
    reader = occ.STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)

    status = reader.ReadFile(str(path))
    if status != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise GeometryLoadError(
            f"OpenCASCADE could not read {path.name} as STEP (status {status}). "
            "The file may be truncated, or not STEP at all."
        )
    if not reader.Transfer(document):
        raise GeometryLoadError(
            f"{path.name} was read but no product structure could be transferred. "
            "The file may contain only unreferenced geometry."
        )

    shape_tool = static(occ.XCAFDoc_DocumentTool, "ShapeTool")(document.Main())

    free_shapes = occ.TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    if free_shapes.Length() == 0:
        raise GeometryLoadError(
            f"{path.name} contains no top-level shapes. Nothing was imported."
        )

    declared_unit = parse_declared_unit(path)
    assembly = Assembly(
        source_path=path,
        unit=LengthUnit.MILLIMETRE,
        unit_confidence=(
            UnitConfidence.DECLARED if declared_unit else UnitConfidence.ASSUMED
        ),
        declared_unit=declared_unit,
    )
    if declared_unit is None:
        assembly.warnings.append(
            "No length unit was found in the STEP header. Geometry was read as "
            "millimetres; confirm that before trusting any dimension."
        )

    counter = _Counter()
    for i in range(1, free_shapes.Length() + 1):
        label = free_shapes.Value(i)
        component = _read_label(
            shape_tool, label, Placement.identity(), (), counter, assembly
        )
        if component is not None:
            assembly.roots.append(component)

    if not assembly.parts():
        raise GeometryLoadError(
            f"{path.name} imported a component tree with no geometry in it."
        )

    assembly.notes.append(
        f"{len(assembly.components())} tree nodes, {assembly.part_count} with geometry."
    )
    return assembly


class _Counter:
    """Hands out stable component indices in traversal order."""

    def __init__(self) -> None:
        self.value = -1

    def next(self) -> int:
        self.value += 1
        return self.value


def _read_label(shape_tool: Any, label: Any, parent_placement: Placement,
                parent_path: tuple[str, ...], counter: _Counter,
                assembly: Assembly) -> Component | None:
    """Convert one OCAF label and its subtree into a :class:`Component`.

    ``parent_placement`` is already composed from the root, so each component's own
    placement is the parent's composed with its local one.
    """
    name = _label_name(label) or f"component_{counter.value + 1}"
    local = _label_placement(shape_tool, label, assembly)
    placement = parent_placement.compose(local)
    path = parent_path + (name,)

    component = Component(
        index=counter.next(),
        name=name,
        placement=placement,
        path=path,
    )

    # A component label (an instance) refers to a part or subassembly definition.
    # The structure lives on the referred label; the placement lives on this one.
    definition = label
    referred = occ.TDF_Label()
    if shape_tool.IsReference_s(label) and shape_tool.GetReferredShape_s(label, referred):
        definition = referred
        if not _label_name(label):
            component.name = _label_name(referred) or component.name
            component.path = parent_path + (component.name,)

    if shape_tool.IsAssembly_s(definition):
        children = occ.TDF_LabelSequence()
        shape_tool.GetComponents_s(definition, children)
        for i in range(1, children.Length() + 1):
            child = _read_label(
                shape_tool, children.Value(i), placement, component.path,
                counter, assembly,
            )
            if child is not None:
                component.children.append(child)
        return component

    shape = shape_tool.GetShape_s(definition)
    if shape is None or shape.IsNull():
        assembly.warnings.append(
            f"Component {component.qualified_name!r} has no geometry and no children; "
            "it was kept in the tree as an empty node."
        )
        return component

    # Position the shape in world coordinates. Analysis and interference checking both
    # want a placed solid, and re-deriving it from the tree at every use is how a
    # placement eventually gets applied twice.
    component.shape = _transformed(shape, placement)
    try:
        volume, _, _ = volume_properties(component.shape)
        component.volume = float(volume)
        component.bounding_box = bounding_box(component.shape)
    except Exception as exc:  # pragma: no cover - depends on the geometry
        assembly.warnings.append(
            f"Could not measure component {component.qualified_name!r}: {exc}"
        )
    return component


def _label_name(label: Any) -> str:
    """Read the OCAF name attribute, or an empty string."""
    attribute = occ.TDataStd_Name()
    if not label.FindAttribute(static(occ.TDataStd_Name, "GetID")(), attribute):
        return ""
    return str(occ.TCollection_AsciiString(attribute.Get()).ToCString()).strip()


def _label_placement(shape_tool: Any, label: Any, assembly: Assembly) -> Placement:
    """Local placement of a component label, as a :class:`Placement`."""
    location = shape_tool.GetLocation_s(label)
    if location is None or location.IsIdentity():
        return Placement.identity()
    return _placement_from_trsf(location.Transformation(), label, assembly)


def _placement_from_trsf(trsf: Any, label: Any, assembly: Assembly) -> Placement:
    matrix = np.array(
        [[trsf.Value(row, column) for column in range(1, 5)] for row in range(1, 4)],
        dtype=float,
    )
    scale = float(trsf.ScaleFactor())
    if abs(scale - 1.0) > 1.0e-9:
        # Divide the scale out of the rotation block so the orthonormality check in
        # Placement.from_matrix sees the rotation alone, then say loudly that the
        # component is scaled. A scaled instance is a different part: its section
        # dimensions, and therefore its stiffness, are not those of the definition.
        matrix[:, :3] /= scale
        assembly.warnings.append(
            f"Component {_label_name(label) or '<unnamed>'} is placed with a scale "
            f"factor of {scale:.6g}. Its geometry is NOT that of the referenced part; "
            "the scale was dropped and only the rigid placement kept."
        )
    return Placement.from_matrix(matrix)


def _transformed(shape: Any, placement: Placement) -> Any:
    """Return ``shape`` moved by ``placement``, as a new shape."""
    if placement.is_identity:
        return shape
    trsf = occ.gp_Trsf()
    rotation = placement.rotation
    translation = placement.translation
    trsf.SetValues(
        rotation[0][0], rotation[0][1], rotation[0][2], translation[0],
        rotation[1][0], rotation[1][1], rotation[1][2], translation[1],
        rotation[2][0], rotation[2][1], rotation[2][2], translation[2],
    )
    builder = occ.BRepBuilderAPI_Transform(shape, trsf, True)
    return builder.Shape()
