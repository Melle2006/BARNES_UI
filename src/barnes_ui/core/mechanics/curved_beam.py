"""Reduced-order curved-beam mechanics for a joint-spanning flexure.

What this computes
------------------

A flexure whose two ends are built into collars on adjacent phalanges. When the joint
rotates, the collars rotate relative to one another, the flexure is forced to deform,
and it pushes back. This module computes how hard it pushes back: the restoring moment
about the joint axis for a prescribed joint angle.

Method
------

Each member is treated as a planar curved beam, clamped at both ends. That makes it
statically indeterminate to degree three in plane, so the unit-load (Castigliano)
method is used:

1. Release one end, leaving three redundants: two in-plane forces and a moment.
2. Build the 3x3 flexibility matrix by integrating along the centreline,

       C_ij = integral [ m_i m_j / (E I) + n_i n_j / (E A) + k v_i v_j / (G A) ] ds

   where m, n and v are the internal moment, axial force and shear produced by unit
   values of each redundant.
3. The relative end displacement imposed by the joint rotation gives
   ``d = C x``, hence ``x = C^-1 d``.
4. Take the moment of those end actions about the joint axis.

Axial and shear flexibility are included rather than dropped. For a strap of 1 mm depth
over a 28 mm span their contribution is small, but a shallow arch resists end
displacement largely by stretching, and omitting the axial term would overstate the
stiffness of the very configurations the optimiser will be drawn to.

The kinematics: the end on the proximal phalanx is fixed; the end on the distal
phalanx is carried by a rigid rotation of the whole distal body about the joint axis.
So the imposed relative displacement is a function of where the flexure ends sit with
respect to the joint axis -- which is why the joint axis has to be supplied and cannot
be guessed from the flexure alone.

What this is not
----------------

This is a **linear** model: small strain, linear-elastic material at its initial
tangent modulus, and geometry that is not updated as the beam deflects. Its output is
the tangent stiffness at the neutral configuration, and the restoring moment it reports
for a large joint angle is a linear extrapolation of that tangent.

For a TPU flexure at real finger-joint angles none of those assumptions holds well.
Every value this module returns is therefore tagged REDUCED_ORDER_PREDICTION and
carries the small-strain and slender-beam caveats. It is a screening tool for ranking
design variants, and its error against nonlinear FEA is unknown until Phase 3 measures
it on this geometry. The one thing it is genuinely good at is relative comparison,
because the modelling error is largely common to variants of the same family.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..flexure.centerline import Member
from ..material.models import HyperelasticModel
from ..provenance import (
    CAVEAT_SLENDER_BEAM,
    CAVEAT_SMALL_STRAIN,
    Caveat,
    Provenance,
    TaggedValue,
)

logger = logging.getLogger(__name__)

__all__ = [
    "JointAxis",
    "TorqueAngleCurve",
    "FlexureStiffness",
    "analyse_joint_flexure",
    "CAVEAT_LINEAR_KINEMATICS",
    "CAVEAT_NO_CONTACT",
]


CAVEAT_LINEAR_KINEMATICS = Caveat(
    "linear_kinematics",
    "Linear kinematics: the geometry is not updated as the flexure deflects, so the "
    "result is the tangent stiffness at the neutral position extrapolated linearly. "
    "A finger joint operates far outside that regime.",
)
CAVEAT_NO_CONTACT = Caveat(
    "no_contact",
    "Contact is not modelled. The flexure is assumed not to touch the phalanges or "
    "itself anywhere in the motion range.",
)
CAVEAT_PARALLEL_MEMBERS = Caveat(
    "parallel_members",
    "Members are combined by summing their individual restoring moments, which assumes "
    "they deform independently and share no load through the attachment collars. The "
    "collars are treated as rigid.",
)

#: Timoshenko shear coefficient for a rectangular section.
_SHEAR_COEFFICIENT_RECTANGLE = 5.0 / 6.0


@dataclass(frozen=True)
class JointAxis:
    """The axis a joint rotates about.

    STEP files do not carry SolidWorks mates, so this cannot be recovered from a CAD
    export and must be supplied. :func:`suggest_joint_axis_from_collars` offers a
    candidate derived from the attachment geometry, but the user confirms it.
    """

    #: A point on the axis, in model coordinates (mm).
    origin: tuple[float, float, float]
    #: Unit direction of the axis.
    direction: tuple[float, float, float]

    def as_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        origin = np.asarray(self.origin, dtype=float)
        direction = np.asarray(self.direction, dtype=float)
        norm = np.linalg.norm(direction)
        if norm < 1.0e-12:
            raise ValueError("Joint axis direction cannot be zero length.")
        return origin, direction / norm


@dataclass
class FlexureStiffness:
    """Stiffness of a flexure about a joint axis, at the neutral configuration."""

    #: Restoring moment per radian of joint rotation, N.mm/rad.
    rotational_stiffness: float
    #: Per-member contributions to the above, N.mm/rad.
    member_stiffness: tuple[float, ...]
    provenance: Provenance
    caveats: tuple[Caveat, ...]
    notes: list[str] = field(default_factory=list)

    def tagged(self) -> TaggedValue:
        return TaggedValue(
            self.rotational_stiffness, "N.mm/rad", self.provenance,
            caveats=self.caveats, label="Joint rotational stiffness (neutral)",
        )


@dataclass
class TorqueAngleCurve:
    """Restoring torque against joint angle.

    Because the underlying model is linear, this curve is a straight line through the
    origin. It is still produced as a curve rather than a single number so that the
    plotting, export and comparison machinery is identical to what Phase 3's nonlinear
    results will use -- and so that the linearity is visible on the plot rather than
    hidden in a stiffness figure.
    """

    #: Joint angles, radians.
    angles: np.ndarray
    #: Restoring torque at each angle, N.mm.
    torques: np.ndarray
    #: Peak engineering strain in the material at each angle, dimensionless.
    peak_strains: np.ndarray
    provenance: Provenance
    caveats: tuple[Caveat, ...]
    notes: list[str] = field(default_factory=list)

    @property
    def angles_degrees(self) -> np.ndarray:
        return np.degrees(self.angles)

    def torque_at(self, angle_rad: float) -> float:
        return float(np.interp(angle_rad, self.angles, self.torques))

    def tangent_stiffness(self) -> np.ndarray:
        """dM/dtheta along the curve, N.mm/rad."""
        return np.gradient(self.torques, self.angles)

    def secant_stiffness(self, angle_rad: float) -> float:
        """Mean stiffness from neutral out to ``angle_rad``, N.mm/rad."""
        if abs(angle_rad) < 1.0e-12:
            return float(self.tangent_stiffness()[0])
        return self.torque_at(angle_rad) / angle_rad

    def as_rows(self) -> list[dict[str, float]]:
        """Rows for CSV export, with units in the column names."""
        return [
            {
                "angle_deg": float(np.degrees(a)),
                "angle_rad": float(a),
                "restoring_torque_Nmm": float(t),
                "peak_engineering_strain": float(e),
            }
            for a, t, e in zip(self.angles, self.torques, self.peak_strains)
        ]


def analyse_joint_flexure(
    members: Sequence[Member],
    material: HyperelasticModel,
    joint: JointAxis,
    max_angle_rad: float,
    steps: int = 25,
    include_shear: bool = True,
    include_axial: bool = True,
) -> tuple[TorqueAngleCurve, FlexureStiffness]:
    """Compute the torque-angle behaviour of a joint-spanning flexure.

    Parameters
    ----------
    members:
        Centreline profiles from :func:`barnes_ui.core.flexure.extract_members`. Each is
        treated as an independent clamped-clamped curved beam.
    material:
        Supplies the initial Young's modulus and the provenance that every result
        inherits.
    joint:
        The axis the two attachment bodies rotate about.
    max_angle_rad:
        Largest joint rotation to evaluate, radians.
    steps:
        Number of points on the curve.

    Returns
    -------
    The torque-angle curve and the neutral-position stiffness.
    """
    if not members:
        raise ValueError("At least one member is required.")
    if steps < 2:
        raise ValueError("steps must be at least 2.")

    E = material.initial_youngs_modulus
    G = material.initial_shear_modulus
    origin, direction = joint.as_arrays()

    per_member: list[float] = []
    peak_strain_per_rad: list[float] = []

    for member in members:
        stiffness, strain_rate = _member_rotational_stiffness(
            member, E, G, origin, direction,
            include_shear=include_shear, include_axial=include_axial,
        )
        per_member.append(stiffness)
        peak_strain_per_rad.append(strain_rate)

    total = float(sum(per_member))
    worst_strain_rate = float(max(peak_strain_per_rad))

    angles = np.linspace(0.0, max_angle_rad, steps)
    torques = total * angles
    strains = worst_strain_rate * np.abs(angles)

    # The material's own caveats are evaluated at the largest strain reached, so an
    # extrapolation warning appears when the motion drives it past its fitted range.
    caveats = (
        material.caveats_for_strain(float(strains.max()))
        + (CAVEAT_SMALL_STRAIN, CAVEAT_SLENDER_BEAM, CAVEAT_LINEAR_KINEMATICS,
           CAVEAT_NO_CONTACT)
    )
    if len(members) > 1:
        caveats = caveats + (CAVEAT_PARALLEL_MEMBERS,)

    # Provenance is the weaker of the material's and the model's own standing. A
    # reduced-order prediction built on measured material is still reduced-order;
    # one built on an assumed material is weaker still.
    provenance = min(material.provenance, Provenance.REDUCED_ORDER_PREDICTION)

    notes = [
        f"{len(members)} member(s), combined rotational stiffness "
        f"{total:.6g} N.mm/rad at the neutral position.",
        f"Initial Young's modulus {E:.6g} MPa from {material.describe()}.",
        "Linear model: the torque-angle relation is a straight line by construction. "
        "Curvature in the real response is a Phase 3 (nonlinear FEA) result.",
    ]
    if len(members) > 1:
        contributions = ", ".join(f"{v:.6g}" for v in per_member)
        notes.append(f"Per-member stiffness (N.mm/rad): {contributions}.")

    curve = TorqueAngleCurve(
        angles=angles, torques=torques, peak_strains=strains,
        provenance=provenance, caveats=caveats, notes=list(notes),
    )
    stiffness = FlexureStiffness(
        rotational_stiffness=total,
        member_stiffness=tuple(per_member),
        provenance=provenance,
        caveats=caveats,
        notes=list(notes),
    )
    return curve, stiffness


def _member_rotational_stiffness(
    member: Member,
    youngs_modulus: float,
    shear_modulus: float,
    joint_origin: np.ndarray,
    joint_direction: np.ndarray,
    include_shear: bool = True,
    include_axial: bool = True,
) -> tuple[float, float]:
    """Restoring moment per radian for one clamped-clamped curved member.

    Returns ``(stiffness, peak_strain_per_radian)``.

    The member is projected into the plane normal to the joint axis, since only
    in-plane deformation resists rotation about that axis. Out-of-plane behaviour is
    not modelled; for the A3 straps, which lie in planes containing the arch and are
    bent about the joint axis, that is the dominant mode.
    """
    positions = member.positions()
    tangents = member.tangents()
    s = member.arc_coordinates()
    areas = member.area_profile()
    inertias = member.inertia_profile()

    # Build an in-plane frame: e1 and e2 span the plane normal to the joint axis.
    e1, e2 = _plane_basis(joint_direction)

    def to_plane(vectors: np.ndarray) -> np.ndarray:
        return np.column_stack([vectors @ e1, vectors @ e2])

    rel = positions - joint_origin
    p = to_plane(rel)                       # (n, 2) position relative to the joint axis
    t = to_plane(tangents)                  # (n, 2) tangent
    t_norm = np.linalg.norm(t, axis=1, keepdims=True)
    t_norm[t_norm < 1.0e-12] = 1.0
    t = t / t_norm
    n_hat = np.column_stack([-t[:, 1], t[:, 0]])   # in-plane normal

    end = p[-1]

    # Unit-action influence coefficients at each station, for redundants
    # x = [F1, F2, M] applied at the released end.
    #   moment about the joint axis direction from an in-plane force F at the end,
    #   measured at station i:  M_i = M + (dx1 * F2 - dx2 * F1), with dx = end - p_i
    delta = end[None, :] - p
    m = np.column_stack([-delta[:, 1], delta[:, 0], np.ones(len(p))])

    # Axial and shear influence: the end force resolved onto the local frame.
    n_inf = np.column_stack([t[:, 0], t[:, 1], np.zeros(len(p))])
    v_inf = np.column_stack([n_hat[:, 0], n_hat[:, 1], np.zeros(len(p))])

    EI = youngs_modulus * inertias
    EA = youngs_modulus * areas
    GA = shear_modulus * areas * _SHEAR_COEFFICIENT_RECTANGLE

    integrand = m[:, :, None] * m[:, None, :] / EI[:, None, None]
    if include_axial:
        integrand = integrand + n_inf[:, :, None] * n_inf[:, None, :] / EA[:, None, None]
    if include_shear:
        integrand = integrand + v_inf[:, :, None] * v_inf[:, None, :] / GA[:, None, None]

    flexibility = np.trapezoid(integrand, s, axis=0)

    # Imposed relative motion for a unit joint rotation. The released end is carried by
    # a rigid rotation of the distal body about the joint axis, so to first order its
    # in-plane displacement is the cross product of the rotation with its position
    # vector, and its section rotates by the same angle.
    imposed = np.array([-end[1], end[0], 1.0])

    try:
        actions = np.linalg.solve(flexibility, imposed)
    except np.linalg.LinAlgError as exc:
        # The most common cause is a genuinely straight member analysed with the axial
        # term switched off. For a straight centreline the axial redundant generates no
        # bending moment anywhere, so with no axial flexibility that degree of freedom
        # has no stiffness at all and the matrix is singular. That is correct physics
        # rather than a numerical accident, so say so instead of blaming the axis.
        straightness = member.curvature_ratio
        if not include_axial and straightness < 1.0001:
            raise ValueError(
                "The flexibility matrix is singular because this member is straight "
                f"(arc/chord = {straightness:.6f}) and axial flexibility is disabled. "
                "A straight member resists end displacement along its own axis purely "
                "by stretching, so include_axial must be True for it. Re-run with "
                "include_axial=True."
            ) from exc
        raise ValueError(
            "The member's flexibility matrix is singular, which means its centreline "
            "is degenerate in the plane of rotation -- check that the joint axis "
            "direction is not parallel to the plane the member curves in."
        ) from exc

    # Restoring moment about the joint axis is the moment of the end actions about it.
    stiffness = float(actions[2] + end[0] * actions[1] - end[1] * actions[0])

    # Peak strain per radian, from the largest bending moment along the member.
    moments = m @ actions
    _, depths = zip(*[st.section.equivalent_rectangle for st in member.stations])
    half_depth = np.asarray(depths, dtype=float) / 2.0
    bending_strain = np.abs(moments) * half_depth / (youngs_modulus * inertias)
    peak_strain = float(np.max(bending_strain))

    return abs(stiffness), peak_strain


def _plane_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal vectors spanning the plane normal to ``axis``."""
    seed = np.zeros(3)
    seed[int(np.argmin(np.abs(axis)))] = 1.0
    e1 = np.cross(axis, seed)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    e2 /= np.linalg.norm(e2)
    return e1, e2


def suggest_joint_axis_from_collars(
    collar_centres: Sequence[Sequence[float]],
    axis_direction: Sequence[float],
) -> JointAxis:
    """Propose a joint axis midway between two attachment collars.

    This is a **suggestion for the user to confirm**, not a determination. Two collars
    being on either side of a joint does not establish where its axis is; the axis
    could be offset dorsally or palmarly from the line joining the collar centres, and
    a millimetre of offset changes the moment arm and hence the torque.

    The caller gets a candidate so that the workflow can run and the axis can be seen
    in the viewport, which is a far better way to catch a wrong axis than a number.
    """
    centres = np.asarray(collar_centres, dtype=float)
    if centres.shape[0] != 2:
        raise ValueError("Exactly two collar centres are required.")
    midpoint = centres.mean(axis=0)
    return JointAxis(
        origin=(float(midpoint[0]), float(midpoint[1]), float(midpoint[2])),
        direction=tuple(float(v) for v in axis_direction),
    )
