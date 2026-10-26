"""Exception types raised by CAD loaders.

These are deliberately distinct from one another so the GUI can respond differently to
each: an unsupported format wants a "here are the formats we read" message, while a
failed parse wants "here is how to re-export".

The guiding rule is that every message tells the user what to *do*, not merely what
went wrong. A bare ``RuntimeError: transfer failed`` is useless to the person who has
to fix the export.
"""

from __future__ import annotations

__all__ = [
    "CadError",
    "UnsupportedFormatError",
    "GeometryLoadError",
    "InvalidGeometryError",
    "KernelUnavailableError",
]


class CadError(Exception):
    """Base class for every CAD-related failure."""


class UnsupportedFormatError(CadError):
    """The file extension is not one this application reads."""


class GeometryLoadError(CadError):
    """The file exists and the format is supported, but it could not be read.

    Covers corrupted files, truncated transfers, and exports that contain nothing
    transferable.
    """


class InvalidGeometryError(CadError):
    """The file loaded, but what came out cannot be used.

    Raised only when there is genuinely nothing to show. Survivable problems -- an
    invalid face, a missing unit declaration -- are attached to the model as warnings
    instead, because the user generally needs to see the model to diagnose them.
    """


class KernelUnavailableError(CadError):
    """The OpenCASCADE kernel is not installed, so B-rep formats cannot be read."""
