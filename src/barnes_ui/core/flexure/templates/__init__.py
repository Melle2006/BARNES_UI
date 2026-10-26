"""Parametric flexure design templates.

Templates generate geometry from parameters rather than morphing an imported solid.
Stretching a solid to fit distorts cross-sections, and bending stiffness scales with
the cube of width, so a modest distortion is a large unintended stiffness change.
"""

from .meander import MeanderError, MeanderParameters, build_meander

__all__ = ["MeanderError", "MeanderParameters", "build_meander"]
