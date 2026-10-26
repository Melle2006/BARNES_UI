"""CAD import, inspection and tessellation."""

from .model import (
    BoundingBox,
    CadFormat,
    GeometryModel,
    GeometryWarning,
    SolidInfo,
    TopologyCounts,
    WarningSeverity,
)
from .registry import file_dialog_filter, load_geometry, supported_extensions

__all__ = [
    "BoundingBox",
    "CadFormat",
    "GeometryModel",
    "GeometryWarning",
    "SolidInfo",
    "TopologyCounts",
    "WarningSeverity",
    "file_dialog_filter",
    "load_geometry",
    "supported_extensions",
]
