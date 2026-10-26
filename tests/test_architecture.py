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
