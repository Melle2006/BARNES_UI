"""Shared test fixtures.

Test geometry is generated here rather than committed as binary files. Generated
fixtures have exactly known properties -- a 10x20x3 box has a volume of 600 mm^3 and
nothing has to be taken on trust -- which is what lets the tests assert real numbers
instead of golden values nobody can verify.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from barnes_ui.core.cad._occ import KERNEL_AVAILABLE

requires_kernel = pytest.mark.skipif(
    not KERNEL_AVAILABLE,
    reason="OpenCASCADE (cadquery-ocp) is not installed",
)


#: Dimensions of the reference box, in millimetres. Chosen with three different edge
#: lengths so that an axis-swap bug cannot hide behind symmetry.
BOX_X, BOX_Y, BOX_Z = 10.0, 20.0, 3.0
BOX_VOLUME = BOX_X * BOX_Y * BOX_Z                       # 600 mm^3
BOX_AREA = 2 * (BOX_X * BOX_Y + BOX_X * BOX_Z + BOX_Y * BOX_Z)   # 580 mm^2


def _make_box_shape():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(BOX_X, BOX_Y, BOX_Z).Shape()


@pytest.fixture(scope="session")
def box_step(tmp_path_factory) -> Path:
    """A STEP file containing a single 10 x 20 x 3 mm box."""
    pytest.importorskip("OCP")
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

    path = tmp_path_factory.mktemp("cad") / "box.step"
    writer = STEPControl_Writer()
    writer.Transfer(_make_box_shape(), STEPControl_StepModelType.STEPControl_AsIs)
    writer.Write(str(path))
    return path


@pytest.fixture(scope="session")
def two_box_step(tmp_path_factory) -> Path:
    """A STEP file with two disconnected boxes, for multi-body handling."""
    pytest.importorskip("OCP")
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(BOX_X, BOX_Y, BOX_Z).Shape())
    builder.Add(
        compound,
        BRepPrimAPI_MakeBox(gp_Pnt(50.0, 0.0, 0.0), 5.0, 5.0, 5.0).Shape(),
    )

    path = tmp_path_factory.mktemp("cad") / "two_boxes.step"
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_StepModelType.STEPControl_AsIs)
    writer.Write(str(path))
    return path


@pytest.fixture(scope="session")
def box_stl(tmp_path_factory) -> Path:
    """An STL of the same box, written with trimesh so no CAD kernel is needed."""
    trimesh = pytest.importorskip("trimesh")

    path = tmp_path_factory.mktemp("cad") / "box.stl"
    mesh = trimesh.creation.box(extents=(BOX_X, BOX_Y, BOX_Z))
    mesh.export(str(path))
    return path


@pytest.fixture(scope="session")
def simple_dxf(tmp_path_factory) -> Path:
    """A DXF with a rectangle and a circle."""
    ezdxf = pytest.importorskip("ezdxf")

    path = tmp_path_factory.mktemp("cad") / "profile.dxf"
    document = ezdxf.new("R2010")
    msp = document.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 20), (0, 20)], close=True
    )
    msp.add_circle((5, 10), radius=2.0)
    document.saveas(str(path))
    return path


@pytest.fixture
def corrupt_step(tmp_path) -> Path:
    """A file with a .step extension that is not a STEP file."""
    path = tmp_path / "broken.step"
    path.write_text("this is definitely not a STEP file\n", encoding="utf-8")
    return path
