"""Per-format CAD readers.

Import loaders through ``barnes_ui.core.cad.registry.load_geometry`` rather than
directly, so that format dispatch stays in one place.
"""

from .errors import (
    CadError,
    GeometryLoadError,
    InvalidGeometryError,
    KernelUnavailableError,
    UnsupportedFormatError,
)

__all__ = [
    "CadError",
    "GeometryLoadError",
    "InvalidGeometryError",
    "KernelUnavailableError",
    "UnsupportedFormatError",
]
