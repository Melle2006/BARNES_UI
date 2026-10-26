"""Reduced-order mechanics.

Separated from the FEA package on purpose: these are fast screening models whose
error against a high-fidelity solution is unknown until it is measured. Keeping them
in their own namespace makes it harder to mistake one for the other.
"""

from .curved_beam import (
    FlexureStiffness,
    JointAxis,
    TorqueAngleCurve,
    analyse_joint_flexure,
    suggest_joint_axis_from_collars,
)

__all__ = [
    "FlexureStiffness",
    "JointAxis",
    "TorqueAngleCurve",
    "analyse_joint_flexure",
    "suggest_joint_axis_from_collars",
]
