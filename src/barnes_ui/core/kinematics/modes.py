"""The Mode 1 / Mode 2 separation, enforced by the type system.

Phase 5 criterion 1 says a kinematic preview must be labelled as such and must display
no force or torque. A label is a promise that someone has to keep rendering correctly
forever. A type with no torque field is a promise the compiler keeps.

So :class:`KinematicPose` -- the Mode 1 result -- has nowhere to put a torque, and
:func:`require_mode` is what any function producing force values calls before it
starts. The GUI reads :attr:`SimulationMode.banner` and shows it unconditionally; it
cannot choose to omit it, because the result carries it rather than the widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ..provenance import (
    CAVEAT_NO_VISCOELASTICITY,
    Caveat,
    Provenance,
)

__all__ = [
    "SimulationMode",
    "KinematicPose",
    "ModeError",
    "require_mode",
    "CAVEAT_QUASI_STATIC",
    "CAVEAT_NO_CONTACT_STATE_CHANGE",
    "CAVEAT_RIGID_LINKS",
    "REDUCED_ORDER_CAVEATS",
]


CAVEAT_QUASI_STATIC = Caveat(
    "quasi_static",
    "Quasi-static: inertia is not modelled, so the result describes a motion slow "
    "enough that acceleration forces are negligible.",
)
CAVEAT_NO_CONTACT_STATE_CHANGE = Caveat(
    "no_contact_state_change",
    "The joint is represented as a torque that depends on angle alone. Anything that "
    "changes the contact state mid-motion -- the flexure touching a phalanx, a "
    "mechanical stop engaging, self-contact in a turn -- is not represented.",
)
CAVEAT_RIGID_LINKS = Caveat(
    "rigid_links",
    "Links are rigid. Only the joint carries compliance, so deflection of the "
    "phalanges themselves is not included.",
)

#: Every caveat that applies to a Mode 2 result, by construction rather than by
#: whoever remembered to attach them. Phase 5 criterion 5.
REDUCED_ORDER_CAVEATS: tuple[Caveat, ...] = (
    CAVEAT_NO_CONTACT_STATE_CHANGE,
    CAVEAT_QUASI_STATIC,
    CAVEAT_RIGID_LINKS,
    CAVEAT_NO_VISCOELASTICITY,
)


class ModeError(RuntimeError):
    """An operation attempted in a mode that cannot support it."""


class SimulationMode(Enum):
    """What kind of answer a run is capable of giving.

    KINEMATIC_PREVIEW
        Rigid-body motion only. Positions, reach, collisions. No force, ever.

    REDUCED_ORDER
        Motion plus a joint spring condensed from FEA. Torques, with caveats.

    COUPLED_FEA
        A full deformable solve of the assembly. Phase 6, and only where a benchmark
        has been passed -- the member exists so that code can be written against it
        without pretending the capability is available.
    """

    KINEMATIC_PREVIEW = "kinematic_preview"
    REDUCED_ORDER = "reduced_order"
    COUPLED_FEA = "coupled_fea"

    @property
    def label(self) -> str:
        return {
            SimulationMode.KINEMATIC_PREVIEW: "Kinematic preview",
            SimulationMode.REDUCED_ORDER: "Reduced-order dynamics",
            SimulationMode.COUPLED_FEA: "Coupled FEA",
        }[self]

    @property
    def banner(self) -> str:
        """Text the UI must display beside any result produced in this mode."""
        return {
            SimulationMode.KINEMATIC_PREVIEW:
                "KINEMATIC PREVIEW -- geometry only. This animation shows where the "
                "parts go, not what force it takes to put them there. No value on "
                "this screen is a force or a torque.",
            SimulationMode.REDUCED_ORDER:
                "REDUCED-ORDER DYNAMICS -- the joint is a spring fitted to FEA "
                "results. Valid only across the angles the FEA covered, and only "
                "while the contact state does not change.",
            SimulationMode.COUPLED_FEA:
                "COUPLED FEA -- a deformable solve. Valid subject to mesh "
                "convergence and material calibration.",
        }[self]

    @property
    def reports_force(self) -> bool:
        return self is not SimulationMode.KINEMATIC_PREVIEW

    @property
    def result_provenance(self) -> Provenance:
        return {
            SimulationMode.KINEMATIC_PREVIEW: Provenance.GEOMETRIC_MEASUREMENT,
            SimulationMode.REDUCED_ORDER: Provenance.REDUCED_ORDER_PREDICTION,
            SimulationMode.COUPLED_FEA: Provenance.FEA_RESULT,
        }[self]


def require_mode(actual: SimulationMode, *allowed: SimulationMode) -> None:
    """Guard at the top of any function whose output only means something in a mode."""
    if actual not in allowed:
        names = ", ".join(m.label for m in allowed)
        raise ModeError(
            f"{actual.label} cannot produce this result; it requires {names}. "
            "This is not a limitation to work around -- a kinematic preview has no "
            "material in it, so there is no force for it to report."
        )


@dataclass(frozen=True)
class KinematicPose:
    """Where everything is at one instant, and nothing else.

    Deliberately has no torque, force, stress or energy field. Phase 5 criterion 1 is
    satisfied by there being nowhere to put one, which is a stronger guarantee than a
    label.
    """

    #: Joint name -> angle in radians.
    angles: Mapping[str, float]
    #: Component index -> world placement, as a 4x4 row-major matrix.
    placements: Mapping[int, Any] = field(default_factory=dict)
    time: float = 0.0

    mode: SimulationMode = SimulationMode.KINEMATIC_PREVIEW

    def __post_init__(self) -> None:
        if self.mode is not SimulationMode.KINEMATIC_PREVIEW:
            raise ModeError(
                "KinematicPose is the Mode 1 result type and cannot be relabelled as "
                "something stronger. A pose with a torque attached belongs in a "
                "JointResponse."
            )

    @property
    def banner(self) -> str:
        return self.mode.banner

    def angle_degrees(self, joint: str) -> float:
        import math

        return math.degrees(self.angles[joint])
