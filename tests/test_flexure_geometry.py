"""Cross-section and centreline extraction tests.

The headline test here is
:meth:`TestObliqueVersusNormalCuts.test_axis_normal_cut_overstates_an_inclined_section`,
which demonstrates the error that the two-pass extraction exists to remove.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from barnes_ui.core.flexure.centerline import CenterlineError, extract_members
from barnes_ui.core.flexure.section import section_solid

from conftest import requires_kernel


def _box(dx: float, dy: float, dz: float, origin=(0.0, 0.0, 0.0)):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*origin), dx, dy, dz).Shape()


def _rotated_box(dx: float, dy: float, dz: float, angle_deg: float):
    """A box rotated about the X axis, to create a genuinely inclined member."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

    transform = gp_Trsf()
    transform.SetRotation(
        gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), math.radians(angle_deg)
    )
    return BRepBuilderAPI_Transform(_box(dx, dy, dz), transform, True).Shape()


@requires_kernel
class TestSectionSolid:
    def test_section_of_a_box_has_the_exact_area(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        sections = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                 u_hint=(1.0, 0.0, 0.0))
        assert len(sections) == 1
        assert sections[0].area == pytest.approx(2.0, rel=1e-9)

    def test_second_moment_matches_the_textbook_formula(self) -> None:
        """I = b*h^3/12 for bending about the axis along b.

        Width 2 mm along X (the bending axis) and depth 1 mm along Z gives
        I = 2 * 1^3 / 12 = 0.1666...
        """
        shape = _box(2.0, 30.0, 1.0)
        sections = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                 u_hint=(1.0, 0.0, 0.0))
        assert sections[0].i_bending == pytest.approx(2.0 * 1.0**3 / 12.0, rel=1e-6)

    def test_the_other_second_moment_is_also_correct(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        sections = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                 u_hint=(1.0, 0.0, 0.0))
        assert sections[0].i_vv == pytest.approx(1.0 * 2.0**3 / 12.0, rel=1e-6)

    def test_u_hint_selects_which_moment_is_i_bending(self) -> None:
        """Swapping the hint must swap I_uu and I_vv, not silently keep one of them."""
        shape = _box(2.0, 30.0, 1.0)
        along_x = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                u_hint=(1.0, 0.0, 0.0))[0]
        along_z = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                u_hint=(0.0, 0.0, 1.0))[0]
        assert along_x.i_uu == pytest.approx(along_z.i_vv, rel=1e-6)
        assert along_x.i_vv == pytest.approx(along_z.i_uu, rel=1e-6)

    def test_equivalent_rectangle_recovers_real_dimensions(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        section = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                u_hint=(1.0, 0.0, 0.0))[0]
        width, depth = section.equivalent_rectangle
        assert width == pytest.approx(2.0, rel=1e-6)
        assert depth == pytest.approx(1.0, rel=1e-6)

    def test_a_rectangle_is_fully_rectangular(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        section = section_solid(shape, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                u_hint=(1.0, 0.0, 0.0))[0]
        assert section.rectangularity == pytest.approx(1.0, rel=1e-6)

    def test_plane_missing_the_solid_returns_no_sections(self) -> None:
        """Not an error: sweeping past the end of a member is normal."""
        shape = _box(2.0, 30.0, 1.0)
        assert section_solid(shape, (0.0, 500.0, 0.0), (0.0, 1.0, 0.0)) == []

    def test_two_parallel_members_give_two_regions(self) -> None:
        """How the twin straps are separated from one another."""
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        builder.Add(compound, _box(2.0, 30.0, 1.0, origin=(0.0, 0.0, 0.0)))
        builder.Add(compound, _box(2.0, 30.0, 1.0, origin=(6.0, 0.0, 0.0)))

        sections = section_solid(compound, (0.0, 15.0, 0.0), (0.0, 1.0, 0.0),
                                 u_hint=(1.0, 0.0, 0.0))
        assert len(sections) == 2
        assert all(s.area == pytest.approx(2.0, rel=1e-9) for s in sections)
        xs = sorted(s.centroid[0] for s in sections)
        assert xs[1] - xs[0] == pytest.approx(6.0, rel=1e-6)


@requires_kernel
class TestObliqueVersusNormalCuts:
    """The reason extraction takes two passes."""

    def test_axis_normal_cut_overstates_an_inclined_section(self) -> None:
        """An oblique slice is inflated by 1/cos(theta).

        Measured on the real A3 part before the fix: cutting perpendicular to global Y
        reported 1.000 mm depth at the arch apex and 1.052 mm near the collars, a 5 per
        cent spread on a member whose section is actually constant. Since stiffness
        goes as depth cubed, accepting that would overstate end stiffness by about 16
        per cent, precisely where a clamped arch carries its largest moment.
        """
        angle = 30.0
        shape = _rotated_box(2.0, 30.0, 1.0, angle)

        # Cut perpendicular to global Y: oblique to the member, so inflated.
        oblique = section_solid(shape, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                                u_hint=(1.0, 0.0, 0.0))
        # Cut perpendicular to the member's own axis: the true normal section.
        tangent = (0.0, math.cos(math.radians(angle)), math.sin(math.radians(angle)))
        normal = section_solid(shape, (0.0, 0.0, 0.0), tangent, u_hint=(1.0, 0.0, 0.0))

        assert normal[0].area == pytest.approx(2.0, rel=1e-6)
        assert oblique[0].area == pytest.approx(
            2.0 / math.cos(math.radians(angle)), rel=1e-3
        )
        assert oblique[0].area > normal[0].area * 1.1

    def test_normal_cut_is_angle_independent(self) -> None:
        """Rotating the member must not change its true section."""
        for angle in (0.0, 15.0, 30.0, 45.0):
            shape = _rotated_box(2.0, 30.0, 1.0, angle)
            tangent = (
                0.0, math.cos(math.radians(angle)), math.sin(math.radians(angle))
            )
            section = section_solid(shape, (0.0, 0.0, 0.0), tangent,
                                    u_hint=(1.0, 0.0, 0.0))[0]
            assert section.area == pytest.approx(2.0, rel=1e-6)
            assert section.i_bending == pytest.approx(2.0 / 12.0, rel=1e-5)


@requires_kernel
class TestExtractMembers:
    def test_straight_bar_gives_one_member(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        members = extract_members(shape, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=20)
        assert len(members) == 1

    def test_arc_length_matches_the_sampled_range(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        members = extract_members(shape, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=40)
        assert members[0].arc_length == pytest.approx(26.0, rel=1e-3)

    def test_straight_member_has_unit_curvature_ratio(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        members = extract_members(shape, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=40)
        assert members[0].curvature_ratio == pytest.approx(1.0, abs=1e-6)

    def test_section_properties_are_constant_and_exact(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        members = extract_members(shape, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=30)
        inertia = members[0].inertia_profile()
        assert np.allclose(inertia, 2.0 * 1.0**3 / 12.0, rtol=1e-5)
        assert np.allclose(members[0].area_profile(), 2.0, rtol=1e-6)

    def test_twin_bars_give_two_members_ordered_by_position(self) -> None:
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        builder.Add(compound, _box(2.0, 30.0, 1.0, origin=(0.0, 0.0, 0.0)))
        builder.Add(compound, _box(2.0, 30.0, 1.0, origin=(6.0, 0.0, 0.0)))

        members = extract_members(compound, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=30)
        assert len(members) == 2
        first_x = members[0].positions()[:, 0].mean()
        second_x = members[1].positions()[:, 0].mean()
        assert first_x < second_x

    def test_range_beyond_the_solid_raises_a_clear_error(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        with pytest.raises(CenterlineError, match="No cross-sections were found"):
            extract_members(shape, (0, 1, 0), (1, 0, 0), 100.0, 200.0, samples=10)

    def test_varying_region_count_is_reported_not_guessed(self) -> None:
        """A meander that doubles back must fail loudly rather than mis-group.

        Built here as two bars of different lengths, so the number of regions changes
        partway along the sweep -- the same signature a doubling-back path produces.
        """
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        builder.Add(compound, _box(2.0, 30.0, 1.0, origin=(0.0, 0.0, 0.0)))
        builder.Add(compound, _box(2.0, 12.0, 1.0, origin=(6.0, 0.0, 0.0)))

        with pytest.raises(CenterlineError, match="varies along the sweep"):
            extract_members(compound, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=30)

    def test_too_few_samples_raises(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        with pytest.raises(ValueError, match="At least 4 samples"):
            extract_members(shape, (0, 1, 0), (1, 0, 0), 2.0, 28.0, samples=3)

    def test_inverted_range_raises(self) -> None:
        shape = _box(2.0, 30.0, 1.0)
        with pytest.raises(ValueError, match="greater than start"):
            extract_members(shape, (0, 1, 0), (1, 0, 0), 28.0, 2.0, samples=10)
