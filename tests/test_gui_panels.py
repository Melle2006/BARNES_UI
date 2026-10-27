"""Smoke and behaviour tests for the workflow panels.

Run against Qt's offscreen platform, so they work on a build machine with no
display -- which Phase 1 criterion 6 requires of the whole suite.

These are not pixel tests. What they check is the handful of behaviours the project's
discipline actually depends on and that are easy to break while editing layout code:

* the Mode 1 banner says what the mode cannot do, and comes from the mode rather than
  from the panel;
* a design with a sub-manufacturable feature cannot be built from the panel;
* Mode 2 is unavailable until a joint spring exists;
* the Pareto view refuses to name a winner when the objectives conflict.

A GUI test suite that only asserted "the window constructs" would pass through every
one of those regressions.
"""

from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QTableWidgetItem  # noqa: E402

from barnes_ui.core.flexure.templates.meander import MeanderParameters  # noqa: E402
from barnes_ui.core.kinematics.modes import SimulationMode  # noqa: E402
from barnes_ui.gui.panels.fea_panel import FeaPanel  # noqa: E402
from barnes_ui.gui.panels.optimise_panel import OptimisePanel  # noqa: E402
from barnes_ui.gui.panels.simulation_panel import SimulationPanel  # noqa: E402
from barnes_ui.gui.panels.template_panel import TemplatePanel  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the session. Qt refuses a second one."""
    app = QApplication.instance() or QApplication([])
    yield app


class TestTemplatePanel:
    def test_derived_geometry_matches_the_template(self, qt_app) -> None:
        panel = TemplatePanel()
        parameters = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
        )
        panel.set_parameters(parameters)
        assert panel.parameters() == parameters
        text = panel._derived.text()
        assert f"{parameters.centreline_length:.4f}" in text
        assert f"{parameters.expected_volume:.4f}" in text

    def test_a_sub_manufacturable_design_cannot_be_built(self, qt_app) -> None:
        """Phase 4 criterion 5, at the point the user would act on it."""
        panel = TemplatePanel()
        panel.set_parameters(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=0.2, thickness=1.2)
        )
        assert not panel._build_button.isEnabled()
        assert "not auto-approved" in panel._build_button.toolTip()
        assert "BLOCKING" in panel._safety_output.toPlainText()

    def test_a_manufacturable_design_can_be_built(self, qt_app) -> None:
        panel = TemplatePanel()
        panel.set_parameters(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=1.0, thickness=1.2)
        )
        assert panel._build_button.isEnabled()

    def test_adaptation_reports_what_changed(self, qt_app) -> None:
        panel = TemplatePanel()
        panel.set_parameters(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=1.0, thickness=1.2)
        )
        panel._target_span.setValue(16.0)
        panel._adapt()
        report = panel._adaptation_output.toPlainText()
        assert "pitch" in report
        assert panel.parameters().envelope[1] == pytest.approx(16.0, abs=1e-9)

    def test_impossible_parameters_disable_building(self, qt_app) -> None:
        panel = TemplatePanel()
        panel._pitch.setValue(0.5)
        panel._width.setValue(1.0)
        assert panel.parameters() is None
        assert not panel._build_button.isEnabled()


class TestSimulationPanel:
    def test_the_preview_banner_says_what_it_cannot_do(self, qt_app) -> None:
        """Criterion 1 at the UI: the banner text comes from the mode."""
        panel = SimulationPanel()
        assert panel.mode() is SimulationMode.KINEMATIC_PREVIEW
        assert panel._banner.text() == SimulationMode.KINEMATIC_PREVIEW.banner
        assert "force" in panel._banner.text().lower()

    def test_reduced_order_is_unavailable_without_a_spring(self, qt_app) -> None:
        panel = SimulationPanel()
        panel._mode.setCurrentIndex(1)
        assert panel.mode() is SimulationMode.REDUCED_ORDER
        assert not panel._run_button.isEnabled()
        assert "fitted to FEA results" in panel._run_button.toolTip()

    def test_fitting_a_spring_enables_reduced_order(self, qt_app) -> None:
        panel = SimulationPanel()
        for row, (angle, torque) in enumerate(
            [(0.0, 0.0), (15.0, 1.7), (30.0, 3.6), (45.0, 5.9), (60.0, 8.7)]
        ):
            panel._points.setItem(row, 0, QTableWidgetItem(str(angle)))
            panel._points.setItem(row, 1, QTableWidgetItem(str(torque)))
        panel._fit()
        assert panel.spring() is not None
        panel._mode.setCurrentIndex(1)
        assert panel._run_button.isEnabled()
        assert "Valid from 0.0 to 60.0 deg" in panel._spring_output.toPlainText()

    def test_two_points_are_refused_with_an_explanation(self, qt_app) -> None:
        panel = SimulationPanel()
        for row, (angle, torque) in enumerate([(0.0, 0.0), (30.0, 3.6)]):
            panel._points.setItem(row, 0, QTableWidgetItem(str(angle)))
            panel._points.setItem(row, 1, QTableWidgetItem(str(torque)))
        panel._fit()
        assert panel.spring() is None
        assert "at least three" in panel._spring_output.toPlainText()

    def test_non_numeric_rows_are_reported_not_ignored(self, qt_app) -> None:
        panel = SimulationPanel()
        panel._points.setItem(0, 0, QTableWidgetItem("nonsense"))
        panel._points.setItem(0, 1, QTableWidgetItem("1.0"))
        panel._fit()
        assert "does not contain two numbers" in panel._spring_output.toPlainText()


class TestFeaPanel:
    def test_the_capability_list_covers_every_capability(self, qt_app) -> None:
        from barnes_ui.core.fea.capabilities import Capability

        panel = FeaPanel()
        labels = {
            panel._capabilities.topLevelItem(i).text(0)
            for i in range(panel._capabilities.topLevelItemCount())
        }
        assert labels == {c.label for c in Capability}

    def test_viscoelasticity_is_shown_as_unavailable(self, qt_app) -> None:
        panel = FeaPanel()
        for index in range(panel._capabilities.topLevelItemCount()):
            item = panel._capabilities.topLevelItem(index)
            if "Viscoelastic" in item.text(0):
                assert item.text(1) == "Not available in this solver"
                return
        pytest.fail("Viscoelasticity was not listed")

    def test_the_comparison_appears_once_both_numbers_exist(self, qt_app) -> None:
        """Phase 3 criterion 7, as the user sees it."""
        panel = FeaPanel()
        panel.set_reduced_order_stiffness(7.558)
        panel._update_comparison(6.103)
        text = panel._comparison.text()
        assert "7.558" in text and "6.103" in text
        assert "23.8 % stiff" in text

    def test_no_comparison_without_a_reduced_order_number(self, qt_app) -> None:
        panel = FeaPanel()
        panel._update_comparison(6.103)
        assert "Run the Phase 2" in panel._comparison.text()

    def test_the_axis_point_starts_unset(self, qt_app) -> None:
        """It is an input, not a default.

        A bounding-box centre silently supplied as the axis is what put the A3's
        joint two millimetres above where it belongs, in a run that converged
        perfectly. The window refuses to submit while the point is at the origin.
        """
        panel = FeaPanel()
        assert panel.axis_point() == (0.0, 0.0, 0.0)
        assert "required input, not a default" in _panel_notes(panel)

    def test_the_axis_point_round_trips(self, qt_app) -> None:
        panel = FeaPanel()
        panel.set_axis_point((6.09, 44.935, 5.44))
        assert panel.axis_point() == pytest.approx((6.09, 44.935, 5.44))
        assert panel.settings()["axis_point"] == pytest.approx((6.09, 44.935, 5.44))


class TestOptimisePanel:
    def _panel(self, qt_app) -> OptimisePanel:
        panel = OptimisePanel()
        panel.set_base_design(
            MeanderParameters(run_length=12.0, n_runs=4, pitch=3.0,
                              width=1.0, thickness=1.2)
        )
        return panel

    def test_a_sweep_with_no_base_design_says_so(self, qt_app) -> None:
        panel = OptimisePanel()
        panel._run()
        assert "does not invent one" in panel._summary.text()

    def test_width_alone_does_not_create_a_trade_off(self, qt_app) -> None:
        """Worth asserting, because it is why the next test sweeps run count.

        Centreline length does not depend on width, so sweeping width moves only
        the volume objective and one design dominates the rest. A front of one is
        the correct answer there, and winner() returns it.
        """
        panel = self._panel(qt_app)
        panel._axis_widgets[0][0].setCurrentIndex(1)       # width
        panel._axis_widgets[0][1].setValue(0.8)
        panel._axis_widgets[0][2].setValue(1.6)
        panel._axis_widgets[0][3].setValue(5)
        panel._run()
        assert "1 non-dominated" in panel._front_output.toPlainText()

    def test_conflicting_objectives_refuse_to_name_a_winner(self, qt_app) -> None:
        """Phase 7 criterion 3, as the user sees it.

        Run count is the axis that genuinely trades off: more runs is a longer
        centreline, which the objectives want, and more material, which they do not.
        """
        panel = self._panel(qt_app)
        panel._axis_widgets[0][0].setCurrentIndex(5)       # n_runs
        panel._axis_widgets[0][1].setValue(4)
        panel._axis_widgets[0][2].setValue(8)
        panel._axis_widgets[0][3].setValue(5)
        panel._run()
        text = panel._front_output.toPlainText()
        assert "Best design: there isn't one." in text
        assert "no best one" in text

    def test_inadmissible_rows_are_kept_and_greyed(self, qt_app) -> None:
        panel = self._panel(qt_app)
        panel._axis_widgets[0][1].setValue(0.2)
        panel._axis_widgets[0][2].setValue(1.6)
        panel._axis_widgets[0][3].setValue(4)
        panel._run()
        assert panel._table.rowCount() == 4
        tooltips = [
            panel._table.item(row, 0).toolTip() for row in range(4)
        ]
        assert any("minimum feature size" in t for t in tooltips)

    def test_weights_must_cover_every_objective(self, qt_app) -> None:
        panel = self._panel(qt_app)
        panel._run()
        panel._weights.setText("material_volume=1")
        panel._choose_weighted()
        assert "implicit zero" in panel._front_output.toPlainText()

    def test_complete_weights_choose_a_design(self, qt_app) -> None:
        panel = self._panel(qt_app)
        panel._run()
        panel._weights.setText("material_volume=1, centreline_length=0")
        panel._choose_weighted()
        text = panel._front_output.toPlainText()
        assert "With weights" in text
        assert "These weights are the decision." in text


def _panel_notes(panel) -> str:
    """Every QLabel's text in a panel, joined. For asserting that a warning is on
    screen without coupling the test to the layout."""
    from PySide6.QtWidgets import QLabel

    return " ".join(label.text() for label in panel.findChildren(QLabel))


class TestTemplateToAnalysisPipeline:
    """The whole chain a user walks through, end to end.

    Build a meander from parameters, write it to STEP, read it back through the
    normal importer, trace its centreline and analyse it with the spatial beam
    model. Every link has unit tests; what this checks is that they are connected,
    which is the part that was missing until the GUI work.
    """

    @pytest.fixture(scope="class")
    def built(self, qt_app, tmp_path_factory):
        pytest.importorskip("OCP")
        from barnes_ui.gui.main_window import _template_worker

        parameters = MeanderParameters(
            run_length=12.0, n_runs=4, pitch=3.0, width=1.0, thickness=1.2
        )
        destination = tmp_path_factory.mktemp("template") / "meander.step"
        return _template_worker(parameters, destination)

    def test_the_built_solid_passes_its_own_volume_check(self, built) -> None:
        parameters, model, issue = built
        assert issue is None, issue
        assert model.solids
        assert model.is_analysis_ready

    def test_the_traced_centreline_recovers_the_exact_arc_length(self, built) -> None:
        """Phase 2 criterion 3's standard, applied through the GUI's own worker."""
        from barnes_ui.gui.main_window import _flexure_worker

        parameters, model, _ = built
        settings = {
            "strategy": "trace",
            "seed_point": (0.0, 0.0, parameters.thickness / 2.0),
            "seed_direction": (1.0, 0.0, 0.0),
            "joint_origin": (6.0, 4.5, 0.6),
            "joint_direction": (1.0, 0.0, 0.0),
            "sweep_axis": (0.0, 1.0, 0.0),
            "range_start": 0.0, "range_end": 1.0, "samples": 120,
            "youngs_modulus": 12.0, "max_angle_deg": 30.0, "steps": 10,
            "include_shear": True, "include_axial": True,
        }
        curve, stiffness, members, _ = _flexure_worker(model.solids[0].shape, settings)

        traced = members[0].arc_length
        exact = parameters.centreline_length
        assert traced == pytest.approx(exact, rel=0.005), (
            f"traced {traced:.4f} mm against an exact {exact:.4f} mm"
        )
        assert stiffness.rotational_stiffness > 0.0

    def test_the_result_is_no_stronger_than_the_material(self, built) -> None:
        """A provisional modulus makes every number downstream an assumption."""
        from barnes_ui.core.provenance import Provenance
        from barnes_ui.gui.main_window import _flexure_worker

        parameters, model, _ = built
        settings = {
            "strategy": "trace",
            "seed_point": (0.0, 0.0, parameters.thickness / 2.0),
            "seed_direction": (1.0, 0.0, 0.0),
            "joint_origin": (6.0, 4.5, 0.6),
            "joint_direction": (1.0, 0.0, 0.0),
            "sweep_axis": (0.0, 1.0, 0.0),
            "range_start": 0.0, "range_end": 1.0, "samples": 120,
            "youngs_modulus": 12.0, "max_angle_deg": 30.0, "steps": 10,
            "include_shear": True, "include_axial": True,
        }
        _, stiffness, _, _ = _flexure_worker(model.solids[0].shape, settings)
        assert stiffness.provenance is Provenance.UNVALIDATED_ASSUMPTION
