"""Spatial beam model tests, and the guards that stop the planar model being misused.

The central result recorded here: on a serpentine meander the planar bending-only
model overstates rotational stiffness by a factor of roughly 670. That is not an
approximation degrading gracefully, and the tests assert the planar model refuses such
a member rather than reporting the number.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.flexure.centerline import CenterlineStation, Member
from barnes_ui.core.flexure.section import CrossSection
from barnes_ui.core.material.models import HyperelasticModel, MaterialModelKind
from barnes_ui.core.mechanics.curved_beam import JointAxis, analyse_joint_flexure
from barnes_ui.core.mechanics.spatial_beam import (
    CAVEAT_SAINT_VENANT_TORSION,
    analyse_joint_flexure_spatial,
    member_torsion_fraction,
)
from barnes_ui.core.provenance import Provenance

E_TEST = 100.0
NU_TEST = 0.3
G_TEST = E_TEST / (2.0 * (1.0 + NU_TEST))


def _material() -> HyperelasticModel:
    return HyperelasticModel(
        kind=MaterialModelKind.LINEAR_ELASTIC,
        parameters=(E_TEST, NU_TEST),
        name="test material",
        provenance=Provenance.ANALYTICAL_ESTIMATE,
        caveats=(),
    )


def _rect_section(centroid, tangent, b: float, h: float) -> CrossSection:
    """Rectangular section b along global X, h along global Z, with its tensor."""
    i_x = b * h**3 / 12.0
    i_z = h * b**3 / 12.0
    tensor = ((i_x, 0.0, 0.0), (0.0, i_x + i_z, 0.0), (0.0, 0.0, i_z))
    return CrossSection(
        area=b * h, centroid=tuple(centroid), width_u=b, width_v=h,
        i_uu=i_x, i_vv=i_z, normal=tuple(tangent),
        u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 0.0, 1.0),
        inertia_tensor=tensor,
    )


def _straight_bar(length: float, b: float, h: float, axis: str = "y",
                  samples: int = 400) -> Member:
    t = np.linspace(0.0, length, samples)
    zeros = np.zeros(samples)
    if axis == "y":
        points = np.column_stack([zeros, t, zeros])
        tangent = (0.0, 1.0, 0.0)
    else:
        points = np.column_stack([t, zeros, zeros])
        tangent = (1.0, 0.0, 0.0)

    stations = [
        CenterlineStation(
            s=float(t[i]), position=tuple(points[i]), tangent=tangent,
            section=_rect_section(points[i], tangent, b, h),
        )
        for i in range(samples)
    ]
    return Member(index=0, stations=stations)


def _torsion_constant(b: float, h: float) -> float:
    long_side, short_side = (b, h) if b >= h else (h, b)
    ratio = short_side / long_side
    return long_side * short_side**3 * (
        1.0 / 3.0 - 0.21 * ratio * (1.0 - short_side**4 / (12.0 * long_side**4))
    )


class TestClosedForm:
    def test_pure_torsion_matches_gj_over_l(self) -> None:
        """A bar twisted about its own axis has stiffness GJ/L exactly.

        Placing the joint axis along the bar through its far end makes the imposed
        motion a pure twist with no translation and no bending.
        """
        length, b, h = 50.0, 2.0, 1.0
        member = _straight_bar(length, b, h, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(0.0, 1.0, 0.0))

        _, stiffness = analyse_joint_flexure_spatial(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        expected = G_TEST * _torsion_constant(b, h) / length
        assert stiffness.rotational_stiffness == pytest.approx(expected, rel=1e-5)

    def test_pure_bending_reduces_to_the_planar_result(self) -> None:
        """With the axis perpendicular to the bar, the answer must be 4EI/L.

        This is what confirms the spatial model degenerates correctly: it must agree
        with the planar model wherever the planar model is valid.
        """
        length, b, h = 50.0, 2.0, 1.0
        member = _straight_bar(length, b, h, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(1.0, 0.0, 0.0))

        _, stiffness = analyse_joint_flexure_spatial(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        expected = 4.0 * E_TEST * (b * h**3 / 12.0) / length
        assert stiffness.rotational_stiffness == pytest.approx(expected, rel=1e-3)

    def test_spatial_and_planar_agree_on_a_bending_case(self) -> None:
        length, b, h = 40.0, 2.0, 1.0
        member = _straight_bar(length, b, h, axis="y")
        joint = JointAxis(origin=(0.0, length / 2.0, -6.0), direction=(1.0, 0.0, 0.0))

        _, spatial = analyse_joint_flexure_spatial(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        _, planar = analyse_joint_flexure(
            [member], _material(), joint, 0.01, 3,
            include_shear=False, include_axial=True,
        )
        assert spatial.rotational_stiffness == pytest.approx(
            planar.rotational_stiffness, rel=0.02
        )


class TestTorsionMatters:
    def test_axis_aligned_bar_is_singular_without_torsion(self) -> None:
        """Nothing resists the rotation, so the refusal is correct physics."""
        length = 50.0
        member = _straight_bar(length, 2.0, 1.0, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(0.0, 1.0, 0.0))
        with pytest.raises(ValueError, match="singular"):
            analyse_joint_flexure_spatial(
                [member], _material(), joint, 0.01, 3,
                include_shear=False, include_axial=True, include_torsion=False,
            )

    def test_torsion_caveat_is_attached(self) -> None:
        length = 50.0
        member = _straight_bar(length, 2.0, 1.0, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(0.0, 1.0, 0.0))
        curve, _ = analyse_joint_flexure_spatial([member], _material(), joint, 0.1, 5)
        assert CAVEAT_SAINT_VENANT_TORSION in curve.caveats

    def test_torsion_fraction_distinguishes_the_two_cases(self) -> None:
        along_y = _straight_bar(50.0, 2.0, 1.0, axis="y")
        assert member_torsion_fraction(along_y, (0.0, 1.0, 0.0)) == pytest.approx(1.0)
        assert member_torsion_fraction(along_y, (1.0, 0.0, 0.0)) == pytest.approx(0.0)


class TestPlanarModelRefusesTorsionMembers:
    """The guard added after the planar model silently mis-analysed a meander."""

    def test_refuses_a_bar_running_along_the_joint_axis(self) -> None:
        length = 50.0
        member = _straight_bar(length, 2.0, 1.0, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(0.0, 1.0, 0.0))
        with pytest.raises(ValueError, match="along the joint axis"):
            analyse_joint_flexure([member], _material(), joint, 0.1, 5)

    def test_refusal_names_the_spatial_alternative(self) -> None:
        length = 50.0
        member = _straight_bar(length, 2.0, 1.0, axis="y")
        joint = JointAxis(origin=(0.0, length, 0.0), direction=(0.0, 1.0, 0.0))
        with pytest.raises(ValueError, match="analyse_joint_flexure_spatial"):
            analyse_joint_flexure([member], _material(), joint, 0.1, 5)

    def test_still_accepts_a_proper_bending_member(self) -> None:
        """The guard must not block the A3-style arch it was written around."""
        length = 40.0
        member = _straight_bar(length, 2.0, 1.0, axis="y")
        joint = JointAxis(origin=(0.0, length / 2.0, -6.0), direction=(1.0, 0.0, 0.0))
        _, stiffness = analyse_joint_flexure(
            [member], _material(), joint, 0.1, 5,
            include_shear=False, include_axial=True,
        )
        assert stiffness.rotational_stiffness > 0.0


class TestParallelTransportFrame:
    def test_frame_survives_a_reversal(self) -> None:
        """A Frenet frame flips through a reversal; parallel transport must not.

        Built as a hairpin -- out along +Y, round, back along -Y -- which is the
        reversal a meander is full of.
        """
        from barnes_ui.core.mechanics.spatial_beam import _parallel_transport_frame

        angles = np.linspace(0.0, np.pi, 60)
        out = np.column_stack([
            np.zeros(40), np.linspace(0.0, 20.0, 40), np.zeros(40)
        ])
        turn = np.column_stack([
            2.0 * np.sin(angles), 20.0 + 2.0 * np.sin(angles / 2) * 0, 2.0 - 2.0 * np.cos(angles)
        ])
        points = np.vstack([out, turn])
        tangents = np.gradient(points, axis=0)
        tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)

        normals, binormals = _parallel_transport_frame(tangents)

        # The frame must stay orthonormal and continuous all the way through.
        assert np.allclose(np.einsum("ij,ij->i", normals, tangents), 0.0, atol=1e-9)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-9)
        assert np.allclose(np.linalg.norm(binormals, axis=1), 1.0, atol=1e-9)
        steps = np.einsum("ij,ij->i", normals[:-1], normals[1:])
        assert steps.min() > 0.9, "the frame jumped between consecutive stations"

    def test_frame_is_defined_on_a_straight_member(self) -> None:
        """A Frenet normal is undefined where curvature is zero; this must not be."""
        from barnes_ui.core.mechanics.spatial_beam import _parallel_transport_frame

        tangents = np.tile(np.array([0.0, 1.0, 0.0]), (50, 1))
        normals, binormals = _parallel_transport_frame(tangents)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)
        assert np.allclose(np.einsum("ij,ij->i", normals, tangents), 0.0, atol=1e-12)


class TestSectionProperties:
    def test_torsion_constant_matches_the_square_reference(self) -> None:
        """Known result for a square: J = 0.1406 * a^4."""
        section = _rect_section((0, 0, 0), (0, 1, 0), 1.0, 1.0)
        assert section.torsion_constant == pytest.approx(0.1406, rel=0.01)

    def test_torsion_constant_tends_to_the_thin_strip_limit(self) -> None:
        """J -> b*h^3/3 as the aspect ratio grows."""
        thin = _rect_section((0, 0, 0), (0, 1, 0), 40.0, 1.0)
        assert thin.torsion_constant == pytest.approx(40.0 / 3.0, rel=0.05)

    def test_second_moment_about_an_arbitrary_axis(self) -> None:
        section = _rect_section((0, 0, 0), (0, 1, 0), 2.0, 1.0)
        assert section.second_moment_about((1, 0, 0)) == pytest.approx(2.0 / 12.0)
        assert section.second_moment_about((0, 0, 1)) == pytest.approx(8.0 / 12.0)

    def test_missing_tensor_raises_rather_than_guessing(self) -> None:
        bare = CrossSection(
            area=2.0, centroid=(0, 0, 0), width_u=2.0, width_v=1.0,
            i_uu=2 / 12, i_vv=8 / 12, normal=(0, 1, 0),
            u_axis=(1, 0, 0), v_axis=(0, 0, 1),
        )
        with pytest.raises(ValueError, match="no inertia tensor"):
            bare.second_moment_about((1, 0, 0))
