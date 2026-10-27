"""Generate the reference PIP-joint assembly used to verify assembly import.

Why a generated assembly
------------------------

Phase 4 criterion 1 asks that component placement survive import to better than
0.01 mm, measured against SolidWorks. That comparison needs a SolidWorks assembly
export, which this project does not yet have (item 2 of docs/06-required-inputs.md).

A generated assembly cannot substitute for that -- it proves nothing about how
SolidWorks writes its placements. What it *can* do is prove the import side: the
placements written into the file are known exactly, to machine precision, so any
discrepancy after a round trip is the reader's and nothing else's. That is a strictly
sharper test of this code than a spot-checked reference point, and it leaves exactly
one untested link in the chain, named and visible, rather than a vague overall doubt.

The geometry
------------

A deliberately plain stand-in for a PIP joint: two rectangular phalanges with a gap
between them, and a flat strap spanning the gap. Plain because the point is the
placements, and a shape whose volume is ``a*b*c`` is one whose import can be checked by
arithmetic.

    python scripts/make_reference_assembly.py
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barnes_ui.core.cad._occ import occ, require_kernel, static  # noqa: E402

#: Proximal phalanx, in mm.
PROXIMAL_SIZE = (12.0, 20.0, 10.0)
#: Distal phalanx, in mm.
DISTAL_SIZE = (12.0, 18.0, 10.0)
#: Flexure strap spanning the gap, in mm.
STRAP_SIZE = (8.0, 10.0, 1.0)

#: Gap between the two phalanges along Y, in mm. The strap spans it.
JOINT_GAP = 6.0

#: Rotation applied to the distal phalanx about the joint axis, in degrees.
#:
#: Non-zero on purpose. A placement check against an assembly whose every component
#: sits at the identity would pass even if the reader dropped rotations entirely.
DISTAL_FLEXION_DEG = 15.0


def _box(dx: float, dy: float, dz: float):
    """A box with one corner at the origin."""
    return occ.BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def _trsf(translation=(0.0, 0.0, 0.0), axis_point=None, axis_dir=(1.0, 0.0, 0.0),
          angle_deg: float = 0.0):
    """Rotation about an axis followed by a translation, as a ``gp_Trsf``."""
    transform = occ.gp_Trsf()
    if angle_deg:
        point = occ.gp_Pnt(*(axis_point or (0.0, 0.0, 0.0)))
        axis = occ.gp_Ax1(point, occ.gp_Dir(*axis_dir))
        transform.SetRotation(axis, math.radians(angle_deg))
    if any(translation):
        shift = occ.gp_Trsf()
        shift.SetTranslation(occ.gp_Vec(*translation))
        transform = shift.Multiplied(transform)
    return transform


def build(path: Path) -> Path:
    require_kernel()

    document = occ.TDocStd_Document(occ.TCollection_ExtendedString("barnes"))
    tool = static(occ.XCAFDoc_DocumentTool, "ShapeTool")(document.Main())

    def add_part(shape, name: str):
        label = tool.AddShape(shape, False)
        static(occ.TDataStd_Name, "Set")(label, occ.TCollection_ExtendedString(name))
        return label

    proximal = add_part(_box(*PROXIMAL_SIZE), "proximal_phalanx")
    distal = add_part(_box(*DISTAL_SIZE), "distal_phalanx")
    strap = add_part(_box(*STRAP_SIZE), "flexure_strap")

    # The joint axis runs along X at the middle of the gap, halfway up the phalanges.
    axis_point = (
        0.0,
        PROXIMAL_SIZE[1] + 0.5 * JOINT_GAP,
        0.5 * PROXIMAL_SIZE[2],
    )

    assembly_label = tool.NewShape()
    static(occ.TDataStd_Name, "Set")(
        assembly_label, occ.TCollection_ExtendedString("pip_joint")
    )

    placements = {
        "proximal_phalanx": _trsf(),
        "flexure_strap": _trsf(
            translation=(
                0.5 * (PROXIMAL_SIZE[0] - STRAP_SIZE[0]),
                PROXIMAL_SIZE[1] + 0.5 * (JOINT_GAP - STRAP_SIZE[1]),
                PROXIMAL_SIZE[2],
            )
        ),
        "distal_phalanx": _trsf(
            translation=(0.0, PROXIMAL_SIZE[1] + JOINT_GAP, 0.0),
            axis_point=axis_point,
            axis_dir=(1.0, 0.0, 0.0),
            angle_deg=DISTAL_FLEXION_DEG,
        ),
    }

    for label, name in ((proximal, "proximal_phalanx"),
                        (strap, "flexure_strap"),
                        (distal, "distal_phalanx")):
        location = occ.TopLoc_Location(placements[name])
        component = tool.AddComponent(assembly_label, label, location)
        static(occ.TDataStd_Name, "Set")(
            component, occ.TCollection_ExtendedString(name)
        )

    tool.UpdateAssemblies()

    writer = occ.STEPCAFControl_Writer()
    occ.Interface_Static.SetCVal_s("write.step.unit", "MM")
    if not writer.Transfer(document, occ.STEPControl_StepModelType.STEPControl_AsIs):
        raise SystemExit("STEPCAFControl_Writer refused the document.")
    path.parent.mkdir(parents=True, exist_ok=True)
    status = writer.Write(str(path))
    if status != occ.IFSelect_ReturnStatus.IFSelect_RetDone:
        raise SystemExit(f"Writing {path} failed with status {status}.")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "reference_parts" / "pip_joint_assembly.step",
    )
    args = parser.parse_args(argv)
    written = build(args.out)
    print(f"Wrote {written} ({written.stat().st_size} bytes)")
    print("Expected placements:")
    print("  proximal_phalanx  identity")
    print("  flexure_strap     translation only")
    print(f"  distal_phalanx    {DISTAL_FLEXION_DEG} deg about X through "
          f"(0, {PROXIMAL_SIZE[1] + 0.5 * JOINT_GAP}, {0.5 * PROXIMAL_SIZE[2]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
