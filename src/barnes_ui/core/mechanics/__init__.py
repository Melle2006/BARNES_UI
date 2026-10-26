"""Reduced-order mechanics.

Separated from the FEA package on purpose: these are fast screening models whose error
against a high-fidelity solution is unknown until it is measured.

Two models, and picking the wrong one is not a small mistake:

``analyse_joint_flexure``
    Planar curved beam. Right for a member lying in the plane of rotation and bending
    about the joint axis -- the A3 twin-strap arch. It has no torsion term and refuses
    members that run along the joint axis.

``analyse_joint_flexure_spatial``
    Full spatial beam with torsion and both bending axes. Required for a serpentine
    meander, whose runs lie along the joint axis and twist. On a test meander the
    planar model overstated stiffness by a factor of 670, so this is not a refinement,
    it is the difference between an answer and a wrong answer.
"""

from .curved_beam import (
    FlexureStiffness,
    JointAxis,
    TorqueAngleCurve,
    analyse_joint_flexure,
    suggest_joint_axis_from_collars,
)
from .spatial_beam import analyse_joint_flexure_spatial, member_torsion_fraction

__all__ = [
    "FlexureStiffness",
    "JointAxis",
    "TorqueAngleCurve",
    "analyse_joint_flexure",
    "analyse_joint_flexure_spatial",
    "member_torsion_fraction",
    "suggest_joint_axis_from_collars",
]
