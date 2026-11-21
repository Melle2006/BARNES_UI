"""Render the application in a series of states and save them as PNGs.

The test suite can tell you that a label holds the right words. It cannot tell you
that the label is white text on a white background, that four chips are red the moment
the application opens, or that a sentence overlaps the box below it. All three were
true of the Phase 2 window and all 808 tests passed.

So this is the other half: drive the real widgets into known states, grab the pixels,
and look at them. It runs offscreen, so it needs no display and can be run on a build
machine -- but what it produces is for a person (or a model) to *look* at, not for an
assertion to pass over.

Usage::

    python scripts/visual_check.py [--out DIR] [--only NAME]

Each state is written as ``DIR/<name>.png``. ``--only`` renders one by substring.

What it deliberately does not do
--------------------------------

It does not compare against reference images. A pixel-diff harness on a Qt application
fails on a font-rendering change and passes on a contrast error that makes a panel
unreadable, which is exactly backwards. The images are evidence for a human decision,
and the states below are chosen to be the ones where a mistake would be expensive:
an empty application (what a new user sees first), a stale result (the state the whole
provenance discipline exists to make visible), and a blocked step (where the interface
has to explain itself rather than just refuse).

The 3D viewport renders through VTK and may come out black or empty offscreen. That is
expected; what these images are for is the panels, the header and the workflow bar.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Deliberately NOT forcing the offscreen platform.
#
# Offscreen Qt has no access to the system fonts, so every string renders as a row
# of empty boxes and the images are useless for the thing they exist to check. The
# native platform plus ``WA_DontShowOnScreen`` gives real fonts and the real system
# palette -- which matters even more, since the defects these images first caught
# were hardcoded dark-theme colours on a light desktop -- while the window never
# appears. Set QT_QPA_PLATFORM=offscreen before running if there is no display at
# all; the layout will still be right and the text will be boxes.
if os.environ.get("BARNES_VISUAL_OFFSCREEN"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------


def _box_model():
    """A 10 x 20 x 3 mm STEP box, through the real importer."""
    import tempfile

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

    from barnes_ui.core.cad.registry import load_geometry

    path = Path(tempfile.gettempdir()) / "barnes_visual_box.step"
    writer = STEPControl_Writer()
    writer.Transfer(
        BRepPrimAPI_MakeBox(10.0, 20.0, 3.0).Shape(),
        STEPControl_StepModelType.STEPControl_AsIs,
    )
    writer.Write(str(path))
    return load_geometry(path)


def _build_meander(window):
    import tempfile

    from barnes_ui.core.flexure.templates.meander import MeanderParameters
    from barnes_ui.gui.main_window import _template_worker

    parameters = MeanderParameters(
        run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
    )
    window.template_panel.set_parameters(parameters)
    destination = Path(tempfile.gettempdir()) / "barnes_visual_meander.step"
    window._on_template_built(_template_worker(parameters, destination))
    return parameters


def state_empty(window) -> None:
    """What a new user sees. Nothing loaded, nothing done."""


def state_imported(window) -> None:
    window._on_import_finished(_box_model())


def state_generated(window) -> None:
    _build_meander(window)


def state_axis_confirmed(window) -> None:
    from barnes_ui.gui.viewer.selection import SelectionPurpose

    window._on_import_finished(_box_model())
    index = window._purpose_combo.findData(SelectionPurpose.JOINT_AXIS)
    window._purpose_combo.setCurrentIndex(index)
    window._measure_button.setChecked(True)
    window._on_point_picked((0.0, 5.0, 1.5))
    window._on_point_picked((10.0, 5.0, 1.5))
    window._confirm_selection()


def state_measuring(window) -> None:
    """Mid-selection: one point captured, waiting for the second."""
    window._on_import_finished(_box_model())
    window._measure_button.setChecked(True)
    window._on_point_picked((0.0, 5.0, 1.5))


def state_stale_result(window) -> None:
    """The state the provenance discipline exists to make visible."""
    parameters = _build_meander(window)
    window._reduced_order_stiffness = 7.558
    window.template_panel._width.setValue(parameters.width + 0.3)


def state_generation_warning(window) -> None:
    """A generated solid that does not match its own parameters."""
    _build_meander(window)
    window._generation_warning = (
        "measured 61.2043 mm^3 against an exact 74.5646 mm^3"
    )
    window._refresh_workflow()


def state_everything_done(window) -> None:
    _build_meander(window)
    window._reduced_order_stiffness = 7.558
    window._fea_stiffness = 6.103
    window._joint_axis = _FakeAxis()
    window._sweep_row_count = 25
    window._refresh_workflow()


class _FakeAxis:
    """Stands in for a confirmed selection, for the all-complete screenshot."""

    origin = (6.09, 4.5, 0.6)
    direction = (1.0, 0.0, 0.0)


def state_analyse_workspace(window) -> None:
    from barnes_ui.gui.workflow import Workspace

    window._on_import_finished(_box_model())
    window.navigator.set_current(Workspace.ANALYSE)


def state_compare_workspace(window) -> None:
    from barnes_ui.gui.workflow import Workspace

    _build_meander(window)
    window.navigator.set_current(Workspace.COMPARE)


def state_inspect_workspace(window) -> None:
    from barnes_ui.gui.workflow import Workspace

    window._on_import_finished(_box_model())
    window.navigator.set_current(Workspace.INSPECT)


#: name -> (setup, width, height). The two narrow entries are the resize check:
#: a parameter form that truncates its units at 1100 px is a defect, and no
#: assertion in the suite would notice.
STATES = {
    "01-empty": (state_empty, 1600, 980),
    "02-imported": (state_imported, 1600, 980),
    "03-generated": (state_generated, 1600, 980),
    "04-measuring": (state_measuring, 1600, 980),
    "05-axis-confirmed": (state_axis_confirmed, 1600, 980),
    "06-stale-result": (state_stale_result, 1600, 980),
    "07-generation-warning": (state_generation_warning, 1600, 980),
    "08-everything-done": (state_everything_done, 1600, 980),
    "09-analyse": (state_analyse_workspace, 1600, 980),
    "10-compare": (state_compare_workspace, 1600, 980),
    "11-inspect": (state_inspect_workspace, 1600, 980),
    # The window refuses to go below 1120 x 720, so this is the narrowest layout
    # that can actually occur.
    "12-narrow": (state_imported, 1200, 800),
    "13-very-narrow": (state_generated, 1120, 720),
}

#: Widgets worth grabbing on their own, because they are small on a 1600 px
#: screenshot and are where the colour decisions live.
DETAILS = {
    "header": lambda w: w.header,
    "workflow-bar": lambda w: w.workflow_bar,
    "measure-dock": lambda w: w._measure_dock,
}


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def capture(name: str, setup, width: int, height: int, out: Path) -> list[Path]:
    from barnes_ui.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])

    window = MainWindow()
    # Lays out exactly as a shown window does, without ever appearing on the
    # desktop. Qt computes nothing until a widget is shown, so grabbing an unshown
    # window returns the wrong sizes.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(width, height)
    window.show()
    app.processEvents()

    setup(window)
    app.processEvents()
    # Twice: the first pass applies the state, the second lets any layout the
    # state changed settle before the pixels are taken.
    app.processEvents()

    written = [out / f"{name}.png"]
    window.grab().save(str(written[0]))

    if name.startswith("01") or name.startswith("06"):
        for detail, accessor in DETAILS.items():
            widget = accessor(window)
            path = out / f"{name}-{detail}.png"
            widget.grab().save(str(path))
            written.append(path)

    window.viewport.close_viewport()
    window.close()
    window.deleteLater()
    app.processEvents()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "results" / "visual",
        help="Directory for the PNGs (created if absent).",
    )
    parser.add_argument(
        "--only", default="", help="Render only states whose name contains this."
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    for name, (setup, width, height) in STATES.items():
        if args.only and args.only not in name:
            continue
        try:
            for path in capture(name, setup, width, height, args.out):
                print(f"wrote {path}")
        except Exception as exc:  # noqa: BLE001 - one bad state must not stop the rest
            print(f"FAILED {name}: {type(exc).__name__}: {exc}")

    print(f"\n{len(list(args.out.glob('*.png')))} images in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
