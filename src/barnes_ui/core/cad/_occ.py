"""Single point of contact with the OpenCASCADE bindings.

Every OCP import in the project goes through this module. Two reasons:

1. **Binding drift.** OCP exposes C++ static member functions with a trailing ``_s``
   (``BRepGProp.VolumeProperties_s``), but not uniformly -- ``TopoDS.Face`` has no
   suffix. Which names carry the suffix has changed between OCP releases. Isolating
   that here means an upgrade touches one file rather than ten.

2. **Testability without the kernel.** The CAD kernel is a ~200 MB dependency. Keeping
   its imports behind :func:`require_kernel` lets the rest of ``core`` -- units,
   provenance, the data model, the project store -- be imported and tested on a machine
   that has not installed it.

Verified against ``cadquery-ocp`` 8.0.1.1.0 on CPython 3.12 / Windows.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "KERNEL_AVAILABLE",
    "KERNEL_IMPORT_ERROR",
    "require_kernel",
    "occ",
    "static",
]

KERNEL_AVAILABLE = False
KERNEL_IMPORT_ERROR: str | None = None


class _OccNamespace:
    """Lazy holder for the OpenCASCADE classes used by the project.

    Attributes are populated on first access so that merely importing this module does
    not pay the cost of loading the kernel, which is appreciable.
    """

    def __init__(self) -> None:
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        # Imported inside the method on purpose: see the module docstring.
        from OCP.Bnd import Bnd_Box
        from OCP.BRep import BRep_Builder, BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepAlgoAPI import (
            BRepAlgoAPI_Common,
            BRepAlgoAPI_Cut,
            BRepAlgoAPI_Fuse,
            BRepAlgoAPI_Section,
        )
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepGProp import BRepGProp
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.BRepTools import BRepTools
        from OCP.collections import HSequence_TopoDS_Shape
        from OCP.GeomAbs import GeomAbs_SurfaceType
        from OCP.gp import (
            gp_Ax1,
            gp_Ax2,
            gp_Ax3,
            gp_Dir,
            gp_Pln,
            gp_Pnt,
            gp_Trsf,
            gp_Vec,
        )
        # XCAF: the product-structure half of STEP. A plain STEPControl_Reader hands
        # back one shape with every component's placement already baked in, which is
        # fine for a single part and useless for an assembly -- the component tree,
        # the names and the individual placements are all gone. These classes read
        # that structure.
        from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
        from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
        from OCP.TDataStd import TDataStd_Name
        from OCP.TDF import TDF_Label
        # OCP exposes OpenCASCADE's TDF_LabelSequence under its generic-collection
        # name. The upstream C++ name does not exist in the bindings at all, so
        # importing it by that name fails outright rather than degrading.
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer
        from OCP.GProp import GProp_GProps
        from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.IGESControl import IGESControl_Reader
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape

        self.Bnd_Box = Bnd_Box
        self.BRep_Builder = BRep_Builder
        self.BRep_Tool = BRep_Tool
        self.BRepAdaptor_Surface = BRepAdaptor_Surface
        self.BRepAlgoAPI_Common = BRepAlgoAPI_Common
        self.BRepAlgoAPI_Cut = BRepAlgoAPI_Cut
        self.BRepBuilderAPI_Transform = BRepBuilderAPI_Transform
        self.BRepExtrema_DistShapeShape = BRepExtrema_DistShapeShape
        self.BRepAlgoAPI_Fuse = BRepAlgoAPI_Fuse
        self.BRepAlgoAPI_Section = BRepAlgoAPI_Section
        self.BRepPrimAPI_MakeBox = BRepPrimAPI_MakeBox
        self.BRepPrimAPI_MakeCylinder = BRepPrimAPI_MakeCylinder
        self.BRepBndLib = BRepBndLib
        self.BRepBuilderAPI_MakeFace = BRepBuilderAPI_MakeFace
        self.BRepCheck_Analyzer = BRepCheck_Analyzer
        self.BRepGProp = BRepGProp
        self.BRepMesh_IncrementalMesh = BRepMesh_IncrementalMesh
        self.BRepTools = BRepTools
        self.HSequence_TopoDS_Shape = HSequence_TopoDS_Shape
        self.GeomAbs_SurfaceType = GeomAbs_SurfaceType
        self.gp_Ax1 = gp_Ax1
        self.gp_Ax2 = gp_Ax2
        self.gp_Ax3 = gp_Ax3
        self.gp_Dir = gp_Dir
        self.gp_Pln = gp_Pln
        self.gp_Pnt = gp_Pnt
        self.gp_Trsf = gp_Trsf
        self.gp_Vec = gp_Vec
        self.STEPCAFControl_Reader = STEPCAFControl_Reader
        self.STEPCAFControl_Writer = STEPCAFControl_Writer
        self.TCollection_AsciiString = TCollection_AsciiString
        self.TCollection_ExtendedString = TCollection_ExtendedString
        self.TDataStd_Name = TDataStd_Name
        self.TDF_Label = TDF_Label
        self.TDF_LabelSequence = TDF_LabelSequence
        self.TDocStd_Document = TDocStd_Document
        self.XCAFDoc_DocumentTool = XCAFDoc_DocumentTool
        self.STEPControl_StepModelType = STEPControl_StepModelType
        self.STEPControl_Writer = STEPControl_Writer
        self.GProp_GProps = GProp_GProps
        self.ShapeAnalysis_FreeBounds = ShapeAnalysis_FreeBounds
        self.IFSelect_ReturnStatus = IFSelect_ReturnStatus
        self.IGESControl_Reader = IGESControl_Reader
        self.Interface_Static = Interface_Static
        self.STEPControl_Reader = STEPControl_Reader
        self.TopAbs_Orientation = TopAbs_Orientation
        self.TopAbs_ShapeEnum = TopAbs_ShapeEnum
        self.TopExp_Explorer = TopExp_Explorer
        self.TopLoc_Location = TopLoc_Location
        self.TopoDS = TopoDS
        self.TopoDS_Compound = TopoDS_Compound
        self.TopoDS_Shape = TopoDS_Shape
        self._loaded = True

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes not yet set, i.e. before _load() has run.
        self._load()
        try:
            return self.__dict__[name]
        except KeyError as exc:  # pragma: no cover - programming error
            raise AttributeError(
                f"{name!r} is not exposed by the OCC namespace. Add it to "
                "barnes_ui.core.cad._occ._OccNamespace._load()."
            ) from exc


occ = _OccNamespace()


def static(cls: Any, name: str) -> Any:
    """Fetch a C++ static member function, tolerating the ``_s`` suffix convention.

    OCP exposes most statics with a trailing underscore-s, but not all of them, and the
    set has changed across releases. Rather than hard-coding which is which, look for
    both.

        static(occ.BRepGProp, "VolumeProperties")  ->  BRepGProp.VolumeProperties_s
        static(occ.TopoDS, "Face")                 ->  TopoDS.Face
    """
    suffixed = getattr(cls, f"{name}_s", None)
    if suffixed is not None:
        return suffixed
    plain = getattr(cls, name, None)
    if plain is not None:
        return plain
    raise AttributeError(
        f"{cls!r} has neither {name!r} nor {name}_s. The OpenCASCADE binding version "
        "may have changed its naming convention."
    )


def _probe() -> None:
    """Record whether the kernel can be imported, without raising at import time."""
    global KERNEL_AVAILABLE, KERNEL_IMPORT_ERROR
    try:
        import OCP  # noqa: F401

        KERNEL_AVAILABLE = True
    except Exception as exc:  # pragma: no cover - depends on the environment
        KERNEL_AVAILABLE = False
        KERNEL_IMPORT_ERROR = str(exc)


_probe()


def require_kernel() -> None:
    """Raise a useful error if the CAD kernel is missing.

    Called at the top of any function that needs OpenCASCADE. The message names the
    install command, because the alternative is a bare ``ModuleNotFoundError: OCP``
    that tells a new contributor nothing.
    """
    if not KERNEL_AVAILABLE:
        raise RuntimeError(
            "The OpenCASCADE CAD kernel is not available, so STEP, IGES and BREP files "
            "cannot be read.\n\n"
            "Install it with:\n"
            "    pip install cadquery-ocp\n\n"
            f"Import error was: {KERNEL_IMPORT_ERROR}"
        )
