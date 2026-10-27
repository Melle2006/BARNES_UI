"""Workflow state derivation.

``assess`` is a pure function from facts to statuses, so this is where the claim
"these states come from data and not from which panel you last visited" is actually
checked. No Qt here; the widget that renders a workflow is tested in
``test_gui_workspaces.py``.

The tests worth reading first are :class:`TestNothingIsCompleteWithoutEvidence` and
:class:`TestStaleResults`. Between them they pin the two ways a progress indicator
lies: ticking a step because the user walked past it, and leaving a tick in place
after the inputs under it moved.
"""

from __future__ import annotations

import pytest

from barnes_ui.gui.workflow import (
    StepStatus,
    WorkflowFacts,
    WorkflowStep,
    Workspace,
    assess,
)

#: A design that has got as far as a valid generated solid with a confirmed axis.
READY = WorkflowFacts(
    has_model=True,
    model_name="meander.step",
    analysis_ready=True,
    geometry_is_generated=True,
    parameters_match_geometry=True,
    template_parameters_valid=True,
    joint_axis_confirmed=True,
    joint_axis_origin=(6.0, 4.5, 0.6),
    has_base_design=True,
)


def status(facts: WorkflowFacts, step: WorkflowStep) -> StepStatus:
    return assess(facts)[step].status


class TestNothingIsCompleteWithoutEvidence:
    def test_an_empty_project_has_no_complete_steps(self) -> None:
        """The property that makes the indicator worth having.

        There is no fact meaning "the user visited this panel", so there is no way
        to reach Complete by navigating.
        """
        workflow = assess(WorkflowFacts())
        assert workflow.statuses_of(StepStatus.COMPLETE) == ()
        assert not workflow.is_complete

    def test_an_empty_project_blocks_everything_downstream(self) -> None:
        facts = WorkflowFacts()
        assert status(facts, WorkflowStep.GEOMETRY) is StepStatus.NOT_STARTED
        assert status(facts, WorkflowStep.JOINT_AXIS) is StepStatus.BLOCKED
        assert status(facts, WorkflowStep.READINESS) is StepStatus.BLOCKED
        assert status(facts, WorkflowStep.ANALYSIS) is StepStatus.BLOCKED
        assert status(facts, WorkflowStep.COMPARISON) is StepStatus.BLOCKED

    def test_every_step_explains_itself(self) -> None:
        """A status with no detail is a decoration."""
        for facts in (WorkflowFacts(), READY):
            for state in assess(facts):
                assert state.detail, f"{state.step} has no detail"
                assert state.label in state.summary()
                assert state.status.label in state.summary()

    def test_a_blocked_step_is_not_the_users_problem_to_fix_here(self) -> None:
        """Blocked and Needs attention are different claims, deliberately."""
        facts = WorkflowFacts()
        assert not status(facts, WorkflowStep.READINESS).is_actionable
        assert StepStatus.NEEDS_ATTENTION.is_actionable


class TestGeometryStep:
    def test_a_ready_model_completes_the_step(self) -> None:
        assert status(READY, WorkflowStep.GEOMETRY) is StepStatus.COMPLETE

    def test_the_detail_says_whether_it_was_imported_or_generated(self) -> None:
        generated = assess(READY)[WorkflowStep.GEOMETRY].detail
        imported = assess(
            WorkflowFacts(
                has_model=True, model_name="a3.step", analysis_ready=True,
                geometry_is_generated=False,
            )
        )[WorkflowStep.GEOMETRY].detail
        assert "generated from parameters" in generated
        assert "imported" in imported

    def test_an_unready_model_needs_attention_and_lists_why(self) -> None:
        facts = WorkflowFacts(
            has_model=True,
            model_name="scan.stl",
            model_is_exact=False,
            analysis_ready=False,
            readiness_reasons=("STL is a tessellated format, so exact geometric "
                               "queries are unavailable.",),
        )
        state = assess(facts)[WorkflowStep.GEOMETRY]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "tessellated" in state.detail
        assert "Re-export" in state.next_action

    def test_a_model_that_is_unready_for_no_stated_reason_says_so(self) -> None:
        """An empty reason list with ``analysis_ready`` False is itself a defect."""
        facts = WorkflowFacts(has_model=True, analysis_ready=False)
        state = assess(facts)[WorkflowStep.GEOMETRY]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "without giving a reason" in state.detail

    def test_the_tessellation_limitation_is_always_stated(self) -> None:
        for facts in (WorkflowFacts(), READY):
            assert "chord tolerance" in assess(facts)[WorkflowStep.GEOMETRY].limitation


class TestGenerationWarning:
    """A solid that does not match its own parameters must stop the workflow.

    OpenCASCADE will call such a solid valid, so ``analysis_ready`` is True and every
    downstream step would otherwise proceed. The volume check against the exact value
    the parameters imply is the stronger test, and a modal dialog that has been
    dismissed no longer says anything.
    """

    FACTS = WorkflowFacts(
        has_model=True,
        model_name="meander.step",
        analysis_ready=True,
        geometry_is_generated=True,
        template_parameters_valid=True,
        joint_axis_confirmed=True,
        has_base_design=True,
        generation_warning="measured 61.2 mm^3 against an exact 74.6 mm^3",
    )

    def test_the_geometry_step_needs_attention_despite_being_ready(self) -> None:
        assert self.FACTS.analysis_ready
        state = assess(self.FACTS)[WorkflowStep.GEOMETRY]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "61.2" in state.detail
        assert "Do not analyse" in state.next_action

    def test_readiness_and_analysis_are_blocked(self) -> None:
        assert status(self.FACTS, WorkflowStep.READINESS) is StepStatus.BLOCKED
        assert status(self.FACTS, WorkflowStep.ANALYSIS) is StepStatus.BLOCKED

    def test_a_result_cannot_complete_the_analysis_step(self) -> None:
        """Even with a number in hand, a solve of the wrong solid is not a result."""
        import dataclasses

        facts = dataclasses.replace(self.FACTS, reduced_order_stiffness=6.103)
        assert status(facts, WorkflowStep.ANALYSIS) is StepStatus.BLOCKED


class TestParametersStep:
    def test_a_manufacturability_block_is_blocked_with_its_reason(self) -> None:
        facts = WorkflowFacts(
            template_parameters_valid=True,
            template_blocked_reason="a feature below the minimum printable size",
        )
        state = assess(facts)[WorkflowStep.PARAMETERS]
        assert state.status is StepStatus.BLOCKED
        assert "minimum printable size" in state.detail
        assert "minimum printable feature size" in state.next_action

    def test_unbuildable_parameters_need_attention(self) -> None:
        state = assess(WorkflowFacts(template_parameters_valid=False))[
            WorkflowStep.PARAMETERS
        ]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "pitch at or below the width" in state.detail

    def test_valid_but_ungenerated_parameters_are_in_progress(self) -> None:
        state = assess(WorkflowFacts(template_parameters_valid=True))[
            WorkflowStep.PARAMETERS
        ]
        assert state.status is StepStatus.IN_PROGRESS
        assert "Build and display" in state.next_action

    def test_generating_completes_the_step(self) -> None:
        assert status(READY, WorkflowStep.PARAMETERS) is StepStatus.COMPLETE

    def test_an_imported_part_has_no_parameters_and_says_so(self) -> None:
        """Rather than leaving the step looking unfinished all session."""
        facts = WorkflowFacts(
            has_model=True, analysis_ready=True,
            geometry_is_generated=False, template_parameters_valid=True,
        )
        state = assess(facts)[WorkflowStep.PARAMETERS]
        assert state.status is StepStatus.NOT_STARTED
        assert "imported" in state.detail
        assert "does not recover a parametric history" in state.detail


class TestJointAxisStep:
    def test_an_unconfirmed_axis_is_not_started(self) -> None:
        facts = WorkflowFacts(has_model=True, analysis_ready=True)
        state = assess(facts)[WorkflowStep.JOINT_AXIS]
        assert state.status is StepStatus.NOT_STARTED
        assert "Measure dock" in state.next_action

    def test_a_confirmed_axis_completes_and_quotes_its_origin(self) -> None:
        state = assess(READY)[WorkflowStep.JOINT_AXIS]
        assert state.status is StepStatus.COMPLETE
        assert "6.0000" in state.detail
        assert "4.5000" in state.detail

    def test_the_completion_does_not_claim_the_axis_was_measured(self) -> None:
        """It is the midpoint of two surface picks, and the step says so."""
        detail = assess(READY)[WorkflowStep.JOINT_AXIS].detail
        assert "not a measurement of where the joint rotates" in detail

    def test_the_limitation_explains_why_this_is_manual(self) -> None:
        for facts in (WorkflowFacts(), READY):
            limitation = assess(facts)[WorkflowStep.JOINT_AXIS].limitation
            assert "STEP carries no mates" in limitation


class TestReadinessStep:
    def test_geometry_ready_without_an_axis_is_blocked_on_the_axis_step(self) -> None:
        """Readiness is a gate, not a task.

        Needs attention here would outrank the Joint axis step that fixes it, and
        the workflow bar would send the user to Analyse to solve a Design problem.
        """
        facts = WorkflowFacts(has_model=True, analysis_ready=True)
        state = assess(facts)[WorkflowStep.READINESS]
        assert state.status is StepStatus.BLOCKED
        assert "no joint axis" in state.detail
        assert "Joint axis step" in state.next_action

    def test_readiness_never_competes_with_the_step_that_fixes_it(self) -> None:
        facts = WorkflowFacts(has_model=True, analysis_ready=True)
        pending = assess(facts).first_needing_attention()
        assert pending is not None
        assert pending.step is WorkflowStep.JOINT_AXIS

    def test_everything_present_completes(self) -> None:
        assert status(READY, WorkflowStep.READINESS) is StepStatus.COMPLETE

    def test_a_missing_solver_is_a_limitation_not_a_block(self) -> None:
        """The reduced-order model still runs; FEA does not, and nothing is faked."""
        state = assess(READY)[WorkflowStep.READINESS]
        assert state.status is StepStatus.COMPLETE
        assert "CalculiX was not found" in state.detail
        assert "not substituted" in state.limitation

    def test_a_present_solver_is_described_and_has_no_limitation(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY, solver_available=True, solver_description="ccx 2.22"
        )
        state = assess(facts)[WorkflowStep.READINESS]
        assert "ccx 2.22" in state.detail
        assert state.limitation is None


class TestAnalysisStep:
    def test_a_running_analysis_is_in_progress(self) -> None:
        import dataclasses

        facts = dataclasses.replace(READY, analysis_running=True)
        state = assess(facts)[WorkflowStep.ANALYSIS]
        assert state.status is StepStatus.IN_PROGRESS
        assert "cancel" in state.next_action

    def test_no_result_is_not_started(self) -> None:
        assert status(READY, WorkflowStep.ANALYSIS) is StepStatus.NOT_STARTED

    def test_without_a_solver_the_next_action_does_not_offer_fea(self) -> None:
        action = assess(READY)[WorkflowStep.ANALYSIS].next_action
        assert "reduced-order" in action
        assert "CalculiX was not found" in action

    def test_a_result_completes_the_step_and_is_quoted(self) -> None:
        import dataclasses

        facts = dataclasses.replace(READY, reduced_order_stiffness=7.558)
        state = assess(facts)[WorkflowStep.ANALYSIS]
        assert state.status is StepStatus.COMPLETE
        assert "7.558" in state.detail

    def test_both_results_are_quoted_when_both_exist(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY, reduced_order_stiffness=7.558, fea_stiffness=6.103
        )
        detail = assess(facts)[WorkflowStep.ANALYSIS].detail
        assert "7.558" in detail and "6.103" in detail

    def test_a_failed_solve_needs_attention_and_is_not_a_zero(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY, fea_failure="the solve diverged at increment 4"
        )
        state = assess(facts)[WorkflowStep.ANALYSIS]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "diverged" in state.detail
        assert "not a zero-stiffness design" in state.next_action

    def test_the_material_caveat_is_attached_to_every_state(self) -> None:
        import dataclasses

        for facts in (
            WorkflowFacts(),
            READY,
            dataclasses.replace(READY, reduced_order_stiffness=1.0),
        ):
            limitation = assess(facts)[WorkflowStep.ANALYSIS].limitation
            assert "provisional modulus" in limitation


class TestStaleResults:
    """A result stops being current the moment an input under it moves.

    The second way a progress indicator lies, and the more dangerous one: the number
    on screen is real, it was computed correctly, and it is the answer to a question
    about a different design.
    """

    def test_a_stale_result_needs_attention_rather_than_completing(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY,
            reduced_order_stiffness=7.558,
            stale_reason="a design parameter changed after the result was computed",
        )
        state = assess(facts)[WorkflowStep.ANALYSIS]
        assert state.status is StepStatus.NEEDS_ATTENTION
        assert "out of date" in state.detail
        assert "parameter changed" in state.detail

    def test_staleness_outranks_having_a_result(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY,
            reduced_order_stiffness=7.558,
            fea_stiffness=6.103,
            stale_reason="the joint axis was changed",
        )
        assert facts.has_any_result
        assert status(facts, WorkflowStep.ANALYSIS) is StepStatus.NEEDS_ATTENTION

    def test_the_previous_result_is_not_claimed_to_be_deleted(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY, reduced_order_stiffness=7.558, stale_reason="something moved"
        )
        action = assess(facts)[WorkflowStep.ANALYSIS].next_action
        assert "previous result is kept" in action

    def test_a_failure_outranks_staleness(self) -> None:
        """Both are Needs attention; the failure is the more specific thing to say."""
        import dataclasses

        facts = dataclasses.replace(
            READY, fea_failure="no convergence", stale_reason="something moved"
        )
        assert "no convergence" in assess(facts)[WorkflowStep.ANALYSIS].detail


class TestComparisonStep:
    def test_no_base_design_blocks_the_sweep(self) -> None:
        state = assess(WorkflowFacts())[WorkflowStep.COMPARISON]
        assert state.status is StepStatus.BLOCKED
        assert "does not invent one" not in state.detail  # that wording is the panel's
        assert "no base design" in state.detail

    def test_a_base_design_without_a_sweep_is_not_started(self) -> None:
        assert status(READY, WorkflowStep.COMPARISON) is StepStatus.NOT_STARTED

    def test_a_completed_sweep_reports_its_count(self) -> None:
        import dataclasses

        facts = dataclasses.replace(READY, sweep_row_count=25)
        state = assess(facts)[WorkflowStep.COMPARISON]
        assert state.status is StepStatus.COMPLETE
        assert "25 candidate designs" in state.detail
        assert "no winner is named" in state.detail

    def test_the_absence_of_named_variants_is_stated_everywhere(self) -> None:
        """The capability the brief asks for and this build does not have."""
        import dataclasses

        for facts in (
            WorkflowFacts(),
            READY,
            dataclasses.replace(READY, sweep_row_count=4),
        ):
            limitation = assess(facts)[WorkflowStep.COMPARISON].limitation
            assert "Named design variants" in limitation
            assert "not implemented" in limitation


class TestNavigation:
    def test_needs_attention_is_pointed_at_before_merely_unfinished(self) -> None:
        """A problem late in the workflow is still the thing to deal with."""
        import dataclasses

        facts = dataclasses.replace(
            READY, reduced_order_stiffness=1.0, stale_reason="a parameter changed"
        )
        pending = assess(facts).first_needing_attention()
        assert pending is not None
        assert pending.step is WorkflowStep.ANALYSIS

    def test_otherwise_the_earliest_unfinished_step_is_chosen(self) -> None:
        pending = assess(WorkflowFacts()).first_needing_attention()
        assert pending is not None
        assert pending.step is WorkflowStep.GEOMETRY

    def test_a_fully_complete_workflow_points_nowhere(self) -> None:
        import dataclasses

        facts = dataclasses.replace(
            READY,
            solver_available=True,
            solver_description="ccx 2.22",
            reduced_order_stiffness=7.558,
            sweep_row_count=9,
        )
        workflow = assess(facts)
        assert workflow.is_complete, [
            (s.step.label, s.status.label) for s in workflow if s.status
            is not StepStatus.COMPLETE
        ]
        assert workflow.first_needing_attention() is None

    def test_a_blocked_step_is_not_offered_as_the_next_action(self) -> None:
        """There is nothing the user can do about a blocked step where it is."""
        pending = assess(WorkflowFacts(has_model=False)).first_needing_attention()
        assert pending is not None
        assert pending.status is not StepStatus.BLOCKED


class TestShape:
    def test_every_step_is_assessed_exactly_once(self) -> None:
        workflow = assess(WorkflowFacts())
        assert len(workflow) == len(WorkflowStep)
        assert [s.step for s in workflow] == list(WorkflowStep)

    def test_an_unknown_step_raises(self) -> None:
        from barnes_ui.gui.workflow import Workflow

        with pytest.raises(KeyError):
            Workflow(steps=()).state_for(WorkflowStep.GEOMETRY)

    def test_every_step_belongs_to_a_workspace(self) -> None:
        for state in assess(WorkflowFacts()):
            assert isinstance(state.workspace, Workspace)

    def test_the_three_task_workspaces_all_own_at_least_one_step(self) -> None:
        owned = {state.workspace for state in assess(WorkflowFacts())}
        assert {Workspace.DESIGN, Workspace.ANALYSE, Workspace.COMPARE} <= owned

    def test_inspect_owns_no_step(self) -> None:
        """It is a supporting workspace, not a stage of the workflow."""
        owned = {state.workspace for state in assess(WorkflowFacts())}
        assert Workspace.INSPECT not in owned

    def test_every_workspace_describes_itself(self) -> None:
        for workspace in Workspace:
            assert workspace.label
            assert workspace.blurb.endswith(".")

    def test_assess_is_pure(self) -> None:
        """Same facts, same answer; and the facts are not modified."""
        facts = READY
        first = assess(facts)
        second = assess(facts)
        assert first == second
        assert facts == READY
