"""Enforces the core/GUI separation.

``barnes_ui.core`` must be importable and testable without a display and without Qt.
Many projects state this rule and then erode it one convenient import at a time, so
here it is checked mechanically.

The check is a static scan of the source rather than a runtime import check, because
a conditional import inside a function would slip past a runtime check while still
breaking the rule the moment that function is called.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import barnes_ui

#: Packages that engineering code may not depend on.
FORBIDDEN_IN_CORE = {
    "PySide6", "PyQt5", "PyQt6", "shiboken6",
    "pyvista", "pyvistaqt", "vtk", "vtkmodules",
    "matplotlib",
}

CORE_ROOT = Path(barnes_ui.__file__).parent / "core"


def _core_modules() -> list[Path]:
    return sorted(CORE_ROOT.rglob("*.py"))


def _imported_top_level_names(path: Path) -> set[str]:
    """Every top-level package name imported by a module, at any nesting depth.

    Walks the whole AST rather than only module-level statements, so an import tucked
    inside a function body is still found.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which is always within the package.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_core_modules_exist() -> None:
    """Guard against the scan silently passing because it found nothing."""
    modules = _core_modules()
    assert len(modules) >= 8, f"Expected to find core modules, found {len(modules)}"


@pytest.mark.parametrize("module", _core_modules(), ids=lambda p: p.name)
def test_core_does_not_import_gui(module: Path) -> None:
    """No module under core/ may import a GUI or plotting library."""
    imported = _imported_top_level_names(module)
    offending = imported & FORBIDDEN_IN_CORE
    assert not offending, (
        f"{module.relative_to(CORE_ROOT.parent)} imports {sorted(offending)}.\n"
        "Engineering code must stay independent of the GUI so that it remains "
        "testable headless and usable from a script. See docs/04-architecture.md."
    )


def test_core_imports_without_qt() -> None:
    """The core package must import with no Qt application in existence."""
    import importlib

    for name in (
        "barnes_ui.core.units",
        "barnes_ui.core.provenance",
        "barnes_ui.core.cad.model",
        "barnes_ui.core.cad.registry",
        "barnes_ui.core.project.store",
        "barnes_ui.core.logging_setup",
    ):
        importlib.import_module(name)


def test_gui_is_allowed_to_import_core() -> None:
    """The dependency runs one way only; confirm the permitted direction exists."""
    gui_root = Path(barnes_ui.__file__).parent / "gui"
    main_window = gui_root / "main_window.py"
    assert main_window.is_file()
    source = main_window.read_text(encoding="utf-8")
    assert "core" in source, "main_window should depend on the core package"


# ---------------------------------------------------------------------------
# Phase 7 criterion 6: nothing but experimental validation produces that tag
# ---------------------------------------------------------------------------

#: Modules allowed to mention EXPERIMENTALLY_VALIDATED, and why.
_VALIDATION_TAG_OWNERS = {
    # Defines the enum member and documents what it means.
    "provenance.py",
    # The only place that constructs a value carrying it, behind a comparison
    # against a real measured specimen.
    "calibration.py",
}


def test_only_the_calibration_module_can_produce_the_validated_tag() -> None:
    """Phase 7 criterion 6, enforced mechanically.

    EXPERIMENTALLY_VALIDATED means a person compared a prediction against a measured
    part. No calculation can make that true, so no calculation may apply the tag. The
    provenance module's ``downgraded_to`` already refuses to strengthen a tag; this
    closes the other route, which is constructing a fresh TaggedValue with it.

    A scan rather than a runtime check, for the same reason as the GUI scan above: a
    line inside a rarely taken branch would pass a runtime check and still be wrong.
    """
    offenders = []
    for module in _core_modules():
        if module.name in _VALIDATION_TAG_OWNERS:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            named = (
                isinstance(node, ast.Attribute) and node.attr == "EXPERIMENTALLY_VALIDATED"
            ) or (
                isinstance(node, ast.Name) and node.id == "EXPERIMENTALLY_VALIDATED"
            )
            if named:
                offenders.append(
                    f"{module.relative_to(CORE_ROOT)}:{node.lineno}"
                )

    # Prose about the tag is fine and in fact wanted -- this looks for code that
    # names it, which is why it walks the AST instead of grepping. A docstring in
    # material/models.py explaining what the tag means tripped the grep version.
    assert not offenders, (
        "EXPERIMENTALLY_VALIDATED appears outside the modules allowed to produce it:\n"
        + "\n".join(offenders)
        + "\nIf a new module legitimately needs it, the question to answer first is "
        "what physical measurement it is reading."
    )


def test_the_calibration_gate_refuses_without_agreement() -> None:
    """The gate itself, exercised here so the scan above cannot pass vacuously."""
    import math

    import numpy as np

    from barnes_ui.core.material.calibration import (
        CalibrationError,
        MeasurementSeries,
        compare_with_measurement,
    )
    from barnes_ui.core.provenance import Provenance, TaggedValue

    angles = np.linspace(0.0, math.radians(40.0), 9)
    measurement = MeasurementSeries(
        angles=angles, torques=6.0 * angles,
        specimen_id="unit-test", method="synthetic", uncertainty=0.05,
    )
    bad = compare_with_measurement(
        angles, 9.0 * angles, measurement, tolerance=0.02,
        prediction_label="deliberately wrong",
    )
    with pytest.raises(CalibrationError, match="disagrees"):
        bad.validated(TaggedValue(1.0, "N.mm", Provenance.FEA_RESULT), angles[-1])
