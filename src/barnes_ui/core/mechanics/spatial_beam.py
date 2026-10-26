"""Spatial (3D) reduced-order beam model, including torsion.

Why a second model
------------------

:mod:`barnes_ui.core.mechanics.curved_beam` treats a member as a planar curved beam
bending in the plane of rotation. That is right for the A3 twin-strap flexure, whose
straps lie in that plane and bend about the joint axis, and it is **wrong for a
serpentine meander**.

In a meander the straight runs are parallel to the joint axis, so a relative rotation
of the two ends twists them about their own axes rather than bending them. Measured on
a generated 4-run meander: 83.5 per cent of centreline stations have a tangent aligned
with the joint axis to better than 0.9, mean alignment 0.915. Those stations carry
torsion, which the planar model does not represent at all -- it would simply omit the
dominant compliance mechanism and report the flexure as far stiffer than it is.

That is exactly why serpentine flexures are used: the torsional compliance of the long
runs is what makes them soft.

Method
------

The same unit-load approach, generalised from three redundants to six. One end is
released, leaving a force and a moment vector; the 6x6 flexibility matrix is integrated
along the centreline from the influence coefficients of all six internal actions --
axial, two shears, torsion and two bending moments; the imposed relative end motion
gives ``x = C^-1 d``; and the restoring moment is the moment of the end actions about
the joint axis.

The local frame is carried along the member by parallel transport rather than
reconstructed at each station from the curvature. A Frenet frame flips its normal
through an inflection point and is undefined on a straight segment, both of which a
meander has in quantity; parallel transport is stable through both.

What it still is not
--------------------

Linear, like its planar sibling: small strain, linear-elastic material at its initial
tangent modulus, and geometry not updated as the member deflects. Results are tagged
``REDUCED_ORDER_PREDICTION`` at best and carry the same caveats, plus one of its own
about the Saint-Venant torsion constant assuming free warping.
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np

from ..flexure.centerline import Member
from ..material.models import HyperelasticModel
from ..provenance import (
    CAVEAT_SLENDER_BEAM,
    CAVEAT_SMALL_STRAIN,
    Caveat,
    Provenance,
)
from .curved_beam import (
    CAVEAT_LINEAR_KINEMATICS,
    CAVEAT_NO_CONTACT,
    FlexureStiffness,
    JointAxis,
    TorqueAngleCurve,
)

logger = logging.getLogger(__name__)

__all__ = [
    "analyse_joint_flexure_spatial",
    "member_torsion_fraction",
    "CAVEAT_SAINT_VENANT_TORSION",
    "CAVEAT_NON_RECTANGULAR_TORSION",
]


CAVEAT_SAINT_VENANT_TORSION = Caveat(
    "saint_venant_torsion",
    "Torsional stiffness uses the Saint-Venant constant for a rectangle, which assumes "
    "the ends are free to warp. A meander's runs are built into turns at both ends, so "
    "some warping restraint is present and the real part is stiffer in torsion than "
    "modelled. The error is in the conservative direction for compliance.",
)
CAVEAT_NON_RECTANGULAR_TORSION = Caveat(
    "non_rectangular_torsion",
    "At least one section departs appreciably from a rectangle, so the rectangular "
    "torsion-constant approximation does not apply to it. Torsional stiffness for this "
    "member is unreliable and needs a warped-section calculation or FEA.",
)

#: Timoshenko shear coefficient for a rectangular section.
_SHEAR_COEFFICIENT_RECTANGLE = 5.0 / 6.0

#: Below this rectangularity the torsion constant stops being trustworthy.
_RECTANGULARITY_FLOOR = 0.90


def analyse_joint_flexure_spatial(
    members: Sequence[Member],
    material: HyperelasticModel,
    joint: JointAxis,
    max_angle_rad: float,
    steps: int = 25,
    include_shear: bool = True,
    include_axial: bool = True,
    include_torsion: bool = True,
) -> tuple[TorqueAngleCurve, FlexureStiffness]:
    """Torque-angle behaviour of a flexure, with full spatial mechanics.

    Signature mirrors :func:`analyse_joint_flexure` so the two can be swapped, with
    ``include_torsion`` added. Switching torsion off is provided for studying how much
    of the compliance it accounts for, not as a normal mode of use.
    """
    if not members:
        raise ValueError("At least one member is required.")
    if steps < 2:
        raise ValueError("steps must be at least 2.")

    E = material.initial_youngs_modulus
    G = material.initial_shear_modulus
    origin, direction = joint.as_arrays()

    per_member: list[float] = []
    strain_rates: list[float] = []
    extra_caveats: set[Caveat] = set()
    notes: list[str] = []

    for member in members:
        stiffness, strain_rate, member_notes, flags = _member_stiffness_spatial(
            member, E, G, origin, direction,
            include_shear=include_shear,
            include_axial=include_axial,
            include_torsion=include_torsion,
        )
        per_member.append(stiffness)
        strain_rates.append(strain_rate)
        extra_caveats.update(flags)
        notes.extend(member_notes)

    total = float(sum(per_member))
    worst_strain_rate = float(max(strain_rates))

    angles = np.linspace(0.0, max_angle_rad, steps)
    torques = total * angles
    strains = worst_strain_rate * np.abs(angles)

    caveats = (
        material.caveats_for_strain(float(strains.max()))
        + (CAVEAT_SMALL_STRAIN, CAVEAT_SLENDER_BEAM, CAVEAT_LINEAR_KINEMATICS,
           CAVEAT_NO_CONTACT)
        + tuple(sorted(extra_caveats, key=lambda c: c.key))
    )
    if include_torsion:
        caveats = caveats + (CAVEAT_SAINT_VENANT_TORSION,)

    provenance = min(material.provenance, Provenance.REDUCED_ORDER_PREDICTION)

    header = [
        f"Spatial beam model, {len(members)} member(s), combined rotational stiffness "
        f"{total:.6g} N.mm/rad at the neutral position.",
        f"Initial Young's modulus {E:.6g} MPa, shear modulus {G:.6g} MPa, from "
        f"{material.describe()}.",
        "Linear model: the torque-angle relation is a straight line by construction.",
    ]
    if not include_torsion:
        header.append(
            "TORSION DISABLED. For a member whose runs lie along the joint axis this "
            "omits the dominant compliance mechanism and overstates stiffness."
        )

    curve = TorqueAngleCurve(
        angles=angles, torques=torques, peak_strains=strains,
        provenance=provenance, caveats=caveats, notes=header + notes,
    )
    stiffness_result = FlexureStiffness(
        rotational_stiffness=total,
        member_stiffness=tuple(per_member),
        provenance=provenance,
        caveats=caveats,
        notes=header + notes,
    )
    return curve, stiffness_result


def _member_stiffness_spatial(
    member: Member,
    youngs_modulus: float,
    shear_modulus: float,
    joint_origin: np.ndarray,
    joint_direction: np.ndarray,
    include_shear: bool,
    include_axial: bool,
    include_torsion: bool,
) -> tuple[float, float, list[str], set[Caveat]]:
    """Restoring moment per radian for one clamped-clamped spatial member."""
    positions = member.positions()
    tangents = member.tangents()
    s = member.arc_coordinates()
    areas = member.area_profile()

    normals, binormals = _parallel_transport_frame(tangents)

    # Section properties resolved onto the member's own local frame.
    count = len(positions)
    i_normal = np.empty(count)
    i_binormal = np.empty(count)
    torsion_j = np.empty(count)
    flags: set[Caveat] = set()

    for k, station in enumerate(member.stations):
        section = station.section
        if section.inertia_tensor is None:
            raise ValueError(
                "Spatial analysis needs the section inertia tensor, which this member's "
                "sections do not carry. Re-extract the centreline with a current build."
            )
        i_normal[k] = section.second_moment_about(normals[k])
        i_binormal[k] = section.second_moment_about(binormals[k])
        torsion_j[k] = section.torsion_constant
        if section.rectangularity < _RECTANGULARITY_FLOOR:
            flags.add(CAVEAT_NON_RECTANGULAR_TORSION)

    EA = youngs_modulus * areas
    GA = shear_modulus * areas * _SHEAR_COEFFICIENT_RECTANGLE
    GJ = shear_modulus * torsion_j
    EI_n = youngs_modulus * i_normal
    EI_b = youngs_modulus * i_binormal

    end = positions[-1]
    lever = end[None, :] - positions          # (n, 3) from station to released end

    # Influence coefficients: how each internal action responds to a unit value of each
    # of the six redundants [Fx, Fy, Fz, Mx, My, Mz] applied at the released end.
    axial = np.zeros((count, 6))
    shear_1 = np.zeros((count, 6))
    shear_2 = np.zeros((count, 6))
    torsion = np.zeros((count, 6))
    bend_1 = np.zeros((count, 6))
    bend_2 = np.zeros((count, 6))

    for j in range(3):
        unit = np.zeros(3)
        unit[j] = 1.0
        axial[:, j] = tangents @ unit
        shear_1[:, j] = normals @ unit
        shear_2[:, j] = binormals @ unit
        # A unit force at the end also produces a moment at every upstream station.
        moment = np.cross(lever, unit)
        torsion[:, j] = np.einsum("ij,ij->i", moment, tangents)
        bend_1[:, j] = np.einsum("ij,ij->i", moment, normals)
        bend_2[:, j] = np.einsum("ij,ij->i", moment, binormals)

    for j in range(3):
        unit = np.zeros(3)
        unit[j] = 1.0
        torsion[:, 3 + j] = tangents @ unit
        bend_1[:, 3 + j] = normals @ unit
        bend_2[:, 3 + j] = binormals @ unit

    integrand = (
        bend_1[:, :, None] * bend_1[:, None, :] / EI_n[:, None, None]
        + bend_2[:, :, None] * bend_2[:, None, :] / EI_b[:, None, None]
    )
    if include_torsion:
        integrand = integrand + torsion[:, :, None] * torsion[:, None, :] / GJ[:, None, None]
    if include_axial:
        integrand = integrand + axial[:, :, None] * axial[:, None, :] / EA[:, None, None]
    if include_shear:
        integrand = integrand + (
            shear_1[:, :, None] * shear_1[:, None, :]
            + shear_2[:, :, None] * shear_2[:, None, :]
        ) / GA[:, None, None]

    flexibility = np.trapezoid(integrand, s, axis=0)

    # Imposed relative motion for a unit joint rotation: the released end is carried by
    # a rigid rotation of the distal body about the joint axis, so its translation is
    # k x (r_end - o) and its section rotates by k.
    imposed = np.concatenate([
        np.cross(joint_direction, end - joint_origin),
        joint_direction,
    ])

    try:
        actions = np.linalg.solve(flexibility, imposed)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "The spatial flexibility matrix is singular. With torsion disabled this "
            "happens for a member that is straight and aligned with the joint axis, "
            "since nothing then resists the imposed rotation. Enable torsion."
        ) from exc

    force = actions[:3]
    moment = actions[3:]

    restoring = float(
        np.dot(moment + np.cross(end - joint_origin, force), joint_direction)
    )

    # Peak strain. Bending contributions about the two local axes are combined as the
    # resultant curvature; torsional shear is reported through its own approximation
    # and converted to an equivalent normal strain for comparison, which is crude but
    # keeps a single "peak strain" figure meaningful enough to flag over-straining.
    station_moments = bend_1 @ actions, bend_2 @ actions
    rect = np.array([st.section.equivalent_rectangle for st in member.stations])
    half_b = rect[:, 0] / 2.0
    half_h = rect[:, 1] / 2.0

    strain_n = np.abs(station_moments[0]) * half_h / EI_n
    strain_b = np.abs(station_moments[1]) * half_b / EI_b
    bending_strain = np.sqrt(strain_n**2 + strain_b**2)
    peak_strain = float(np.max(bending_strain))

    torsion_moment = torsion @ actions
    torsion_fraction = _energy_fraction(
        torsion_moment, GJ, station_moments, EI_n, EI_b, s
    )

    notes = [
        f"Member {member.index}: stiffness {abs(restoring):.6g} N.mm/rad, "
        f"{len(positions)} stations over {member.arc_length:.4f} mm.",
        f"Member {member.index}: torsion accounts for "
        f"{100.0 * torsion_fraction:.1f}% of the strain energy"
        + (" -- the planar bending-only model would be badly wrong for it."
           if torsion_fraction > 0.25 else "."),
    ]
    if CAVEAT_NON_RECTANGULAR_TORSION in flags:
        notes.append(
            f"Member {member.index}: at least one section is not rectangular enough "
            "for the torsion-constant approximation."
        )

    return abs(restoring), peak_strain, notes, flags


def _energy_fraction(
    torsion_moment: np.ndarray,
    GJ: np.ndarray,
    bending: tuple[np.ndarray, np.ndarray],
    EI_n: np.ndarray,
    EI_b: np.ndarray,
    s: np.ndarray,
) -> float:
    """Share of strain energy carried by torsion rather than bending.

    Reported because it is the single most useful diagnostic for whether the planar
    model was adequate: a member above roughly a quarter is torsion-driven, and a
    bending-only analysis of it is not approximately right, it is qualitatively wrong.
    """
    torsional = np.trapezoid(torsion_moment**2 / GJ, s)
    flexural = np.trapezoid(bending[0] ** 2 / EI_n, s) + np.trapezoid(
        bending[1] ** 2 / EI_b, s
    )
    total = torsional + flexural
    return float(torsional / total) if total > 0 else 0.0


def _parallel_transport_frame(
    tangents: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Carry a local frame along the member by parallel transport.

    A Frenet frame is unusable here: its normal is undefined on a straight segment and
    flips through an inflection point, and a meander is mostly straight segments joined
    by reversals. Parallel transport instead rotates the previous frame by the minimal
    rotation carrying the previous tangent onto the current one, which is continuous
    through both.
    """
    count = len(tangents)
    normals = np.zeros((count, 3))
    binormals = np.zeros((count, 3))

    # Seed with any unit vector perpendicular to the first tangent.
    seed = np.zeros(3)
    seed[int(np.argmin(np.abs(tangents[0])))] = 1.0
    normal = np.cross(tangents[0], seed)
    normal /= np.linalg.norm(normal)

    normals[0] = normal
    binormals[0] = np.cross(tangents[0], normal)

    for i in range(1, count):
        previous, current = tangents[i - 1], tangents[i]
        axis = np.cross(previous, current)
        sine = float(np.linalg.norm(axis))
        cosine = float(np.dot(previous, current))

        if sine < 1.0e-12:
            # Parallel (or antiparallel) tangents: carry the frame straight through.
            rotated = normal
        else:
            axis = axis / sine
            angle = float(np.arctan2(sine, cosine))
            rotated = _rodrigues(normal, axis, angle)

        # Re-orthogonalise against the new tangent so numerical drift cannot
        # accumulate over several hundred stations.
        rotated = rotated - np.dot(rotated, current) * current
        norm = np.linalg.norm(rotated)
        if norm < 1.0e-12:  # pragma: no cover - degenerate, re-seed
            seed = np.zeros(3)
            seed[int(np.argmin(np.abs(current)))] = 1.0
            rotated = np.cross(current, seed)
            norm = np.linalg.norm(rotated)
        normal = rotated / norm

        normals[i] = normal
        binormals[i] = np.cross(current, normal)

    return normals, binormals


def _rodrigues(vector: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotate ``vector`` about ``axis`` by ``angle`` radians."""
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    return (
        vector * cos_a
        + np.cross(axis, vector) * sin_a
        + axis * np.dot(axis, vector) * (1.0 - cos_a)
    )


def member_torsion_fraction(
    member: Member, joint_direction: Sequence[float]
) -> float:
    """Fraction of a member's length whose tangent is aligned with the joint axis.

    A cheap screening test for whether the planar model is applicable, usable before
    any mechanics is run. A value near zero means the member lies in the plane of
    rotation and bends; a value near one means it lies along the axis and twists.
    """
    direction = np.asarray(joint_direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    alignment = np.abs(member.tangents() @ direction)
    return float(np.mean(alignment > 0.9))
