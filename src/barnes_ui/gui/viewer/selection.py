"""Two-point selection as an explicit state machine.

Picking two points in a 3D view looks like one gesture and is actually a small
protocol: arm it, catch a hit, catch a second hit, reject the ones that are not
usable, show a preview, and either commit the result or throw it away. The first
version of this lived as two lines and a list inside ``MainWindow`` and had the
failure that list-plus-two-lines always has -- the list outlived the model it was
measured on, so a point picked before an import could pair with one picked after and
produce a distance between two different parts.

So the protocol is written out here, with no Qt and no VTK, which means the whole of
it is testable headless. The viewport's job is reduced to turning mouse events into
``add_point`` calls and drawing what this object says is captured.

Two things this module deliberately keeps apart
-----------------------------------------------

**A measurement is not a joint definition.** Both are two points. One is a number you
read; the other is an engineering input that the stiffness result is extremely
sensitive to -- two millimetres of axis error changes the reported torque
substantially (README, "Known limitations"). A measurement is therefore readable as
soon as the second point lands, whereas an axis is not available at all until
``confirm()`` has been called. ``confirmed_axis`` returns ``None`` until then, so
there is no route by which an unconfirmed pick reaches an analysis.

**A stale callback is not a pick.** ``begin`` returns a token and ``add_point``
takes one. VTK observers and Qt slots both outlive the thing that registered them, and
a point arriving from a torn-down session is dropped rather than appended.

Coordinates are in the model's own coordinate system and unit, exactly as the picker
reports them; nothing here converts, and the unit string is carried only so that the
messages are not unitless. Points lie on the display tessellation, which is the
accuracy limit this project has always stated for picking -- see
``Viewport.start_point_picking``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "PickOutcome",
    "PointSelectionController",
    "SelectionPurpose",
    "SelectionState",
    "TwoPointSelection",
]

Point = tuple[float, float, float]


class SelectionPurpose(Enum):
    """What a pair of picked points is for.

    The two members share a picking mechanism and share nothing else: the
    tolerances differ, the confirmation requirement differs, and the result type
    differs.
    """

    MEASUREMENT = "measurement"
    JOINT_AXIS = "joint-axis"

    @property
    def label(self) -> str:
        return {
            "measurement": "Point-to-point measurement",
            "joint-axis": "Joint axis definition",
        }[self.value]

    @property
    def requires_confirmation(self) -> bool:
        """Whether the result is unusable until a person has agreed to it."""
        return self is SelectionPurpose.JOINT_AXIS

    @property
    def default_coincidence_tolerance(self) -> float:
        """Smallest separation (mm) that still counts as two distinct points.

        Different by a factor of a hundred thousand between the two purposes, on
        purpose. A measurement of 0.01 mm is a legitimate measurement, so only a
        separation at the level of floating-point noise is refused. A *direction*
        taken from two points 0.01 mm apart is noise multiplied by the reciprocal
        of that separation -- the shorter the baseline, the more the tessellation's
        chord error is amplified into an angle -- so an axis needs a real baseline
        and 0.5 mm is the floor.

        Callers that know the part's size should pass something scaled to it
        instead of relying on these; ``begin`` accepts an override.
        """
        return 1.0e-6 if self is SelectionPurpose.MEASUREMENT else 0.5


class SelectionState(Enum):
    """Where in the protocol the controller is."""

    IDLE = "idle"
    AWAITING_FIRST = "awaiting-first"
    AWAITING_SECOND = "awaiting-second"
    PREVIEW = "preview"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def is_picking(self) -> bool:
        """Whether the viewport should have picking armed in this state.

        ``PREVIEW`` is included: the pair is captured but not committed, and the
        intended recovery from a bad second point is to clear and pick again
        without having to re-arm the tool.
        """
        return self in (
            SelectionState.AWAITING_FIRST,
            SelectionState.AWAITING_SECOND,
            SelectionState.PREVIEW,
        )


class PickOutcome(Enum):
    """What the controller did with a point handed to ``add_point``."""

    #: Not picking, or the token was from a previous session.
    IGNORED = "ignored"
    FIRST_CAPTURED = "first-captured"
    SECOND_CAPTURED = "second-captured"
    #: Too close to the first point to be a second point for this purpose.
    REJECTED_COINCIDENT = "rejected-coincident"
    #: Not three finite numbers.
    REJECTED_INVALID = "rejected-invalid"

    @property
    def captured(self) -> bool:
        return self in (PickOutcome.FIRST_CAPTURED, PickOutcome.SECOND_CAPTURED)


@dataclass(frozen=True)
class TwoPointSelection:
    """A captured pair, and the quantities derived from it.

    Nothing here is rounded or converted. ``distance`` is the Euclidean distance in
    the model's unit; ``direction`` is a unit vector; ``origin`` is the midpoint,
    which is the only origin two points without further information can justify.
    """

    purpose: SelectionPurpose
    first: Point
    second: Point
    unit: str = "mm"

    @property
    def delta(self) -> Point:
        return (
            self.second[0] - self.first[0],
            self.second[1] - self.first[1],
            self.second[2] - self.first[2],
        )

    @property
    def distance(self) -> float:
        dx, dy, dz = self.delta
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @property
    def direction(self) -> Point:
        """Unit vector from the first point to the second.

        Raises ``ValueError`` on a zero-length pair. The controller refuses such a
        pair before one can be constructed, so reaching this is a bug rather than a
        user error, and it should say so loudly instead of returning ``(0, 0, 0)``
        for an analysis to use as an axis.
        """
        length = self.distance
        if length <= 0.0:
            raise ValueError(
                "Two coincident points have no direction. The controller should "
                "have refused this pair."
            )
        dx, dy, dz = self.delta
        return (dx / length, dy / length, dz / length)

    @property
    def origin(self) -> Point:
        return (
            0.5 * (self.first[0] + self.second[0]),
            0.5 * (self.first[1] + self.second[1]),
            0.5 * (self.first[2] + self.second[2]),
        )


def _is_finite_point(point) -> bool:
    try:
        values = tuple(float(v) for v in point)
    except (TypeError, ValueError):
        return False
    return len(values) == 3 and all(math.isfinite(v) for v in values)


def _format_point(point: Point, unit: str) -> str:
    return f"({point[0]:.4f}, {point[1]:.4f}, {point[2]:.4f}) {unit}"


class PointSelectionController:
    """The two-point protocol. No Qt, no VTK, no geometry kernel.

    One instance serves both purposes but only one at a time: ``begin`` replaces
    whatever was in progress, which is what makes switching from measuring to
    defining an axis safe rather than something that leaves half a measurement
    behind.
    """

    def __init__(self, unit: str = "mm") -> None:
        self._unit = unit
        self._state = SelectionState.IDLE
        self._purpose: SelectionPurpose | None = None
        self._points: list[Point] = []
        self._tolerance = 0.0
        self._generation = 0
        self._message = "Point selection is off."
        self._confirmed: TwoPointSelection | None = None

    # -- observation -----------------------------------------------------------

    @property
    def state(self) -> SelectionState:
        return self._state

    @property
    def purpose(self) -> SelectionPurpose | None:
        return self._purpose

    @property
    def points(self) -> tuple[Point, ...]:
        return tuple(self._points)

    @property
    def generation(self) -> int:
        """Token of the current session. Increments on every ``begin``."""
        return self._generation

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def coincidence_tolerance(self) -> float:
        return self._tolerance

    @property
    def is_picking(self) -> bool:
        return self._state.is_picking

    @property
    def message(self) -> str:
        """What the user should be told right now.

        A single string rather than a status code because every state here has
        exactly one thing worth saying, and the alternative -- the panel deciding
        the wording from the state -- is how the instruction and the state drift
        apart.
        """
        return self._message

    @property
    def result(self) -> TwoPointSelection | None:
        """The pair, once both points are captured. ``None`` before that.

        Available in ``PREVIEW``, which is the point: a measurement is readable as
        soon as it exists. See ``confirmed_axis`` for the quantity that is not.
        """
        if len(self._points) < 2:
            return None
        if self._state not in (SelectionState.PREVIEW, SelectionState.COMPLETED):
            return None
        return TwoPointSelection(
            purpose=self._purpose or SelectionPurpose.MEASUREMENT,
            first=self._points[0],
            second=self._points[1],
            unit=self._unit,
        )

    @property
    def confirmed_axis(self) -> TwoPointSelection | None:
        """The joint axis, and only once a person has confirmed it.

        The one accessor an analysis should read. It returns ``None`` for a
        measurement, for an unconfirmed preview, and after any invalidation, so
        there is no path from "two points happened to be picked" to "the solver was
        given an axis".
        """
        if self._state is not SelectionState.COMPLETED:
            return None
        if self._purpose is not SelectionPurpose.JOINT_AXIS:
            return None
        return self._confirmed

    # -- transitions -----------------------------------------------------------

    def set_unit(self, unit: str) -> None:
        """Change the unit the messages quote.

        Does not convert anything. The picker reports coordinates in the model's
        stored unit, and reinterpreting that unit (which the Geometry panel allows
        for formats that declare none) changes what the same numbers mean without
        changing the numbers.
        """
        self._unit = unit

    def begin(
        self,
        purpose: SelectionPurpose,
        *,
        coincidence_tolerance: float | None = None,
    ) -> int:
        """Arm picking for ``purpose``, discarding anything in progress.

        Returns the session token to pass back to ``add_point``.
        """
        self._purpose = purpose
        self._tolerance = (
            purpose.default_coincidence_tolerance
            if coincidence_tolerance is None
            else float(coincidence_tolerance)
        )
        self._points.clear()
        self._confirmed = None
        self._generation += 1
        self._state = SelectionState.AWAITING_FIRST
        self._message = (
            f"{purpose.label}: click the first point on the model. "
            "Left-click, or hover and press P."
        )
        return self._generation

    def add_point(self, point, *, token: int | None = None) -> PickOutcome:
        """Offer a picked point to the controller.

        ``token`` is the value ``begin`` returned. Passing ``None`` skips the check,
        which is convenient in tests and wrong in the viewport.
        """
        if token is not None and token != self._generation:
            # A callback from a session that has already been replaced. Dropping it
            # silently is correct: the user did not do anything, a dead observer did.
            return PickOutcome.IGNORED

        if self._state not in (
            SelectionState.AWAITING_FIRST,
            SelectionState.AWAITING_SECOND,
        ):
            return PickOutcome.IGNORED

        if not _is_finite_point(point):
            self._message = (
                "That pick did not return three finite coordinates, so it was "
                "discarded. The selection is unchanged."
            )
            return PickOutcome.REJECTED_INVALID

        candidate: Point = tuple(float(v) for v in point)  # type: ignore[assignment]

        if self._state is SelectionState.AWAITING_FIRST:
            self._points = [candidate]
            self._state = SelectionState.AWAITING_SECOND
            self._message = (
                f"First point {_format_point(candidate, self._unit)}. "
                "Click the second point."
            )
            return PickOutcome.FIRST_CAPTURED

        first = self._points[0]
        separation = math.dist(first, candidate)
        if separation <= self._tolerance:
            self._message = (
                f"That point is {separation:.6g} {self._unit} from the first, which "
                f"is within the {self._tolerance:g} {self._unit} this "
                f"{(self._purpose or SelectionPurpose.MEASUREMENT).label.lower()} "
                "treats as the same point. The first point is kept; click somewhere "
                "else for the second."
            )
            return PickOutcome.REJECTED_COINCIDENT

        self._points = [first, candidate]
        self._state = SelectionState.PREVIEW
        self._message = self._preview_message()
        return PickOutcome.SECOND_CAPTURED

    def register_miss(self) -> PickOutcome:
        """Record a click that hit no geometry.

        Reported rather than ignored, because a click that produced nothing is
        indistinguishable from a tool that is not working. The state and the
        captured points are untouched -- a miss cannot corrupt a half-finished
        selection.
        """
        if not self.is_picking:
            return PickOutcome.IGNORED
        self._message = (
            "That click missed the model, so nothing was captured. "
            + (
                "Click the first point on the model."
                if self._state is SelectionState.AWAITING_FIRST
                else "The points already picked are unchanged."
            )
        )
        return PickOutcome.IGNORED

    def clear(self) -> None:
        """Drop the captured points but stay armed.

        The ordinary recovery from a misplaced point: the user wants to pick again,
        not to put the tool away.
        """
        if self._purpose is None:
            self.reset()
            return
        self._points.clear()
        self._confirmed = None
        self._state = SelectionState.AWAITING_FIRST
        self._message = (
            f"Cleared. {self._purpose.label}: click the first point on the model."
        )

    def cancel(self) -> None:
        """Abandon the operation. Picking should be disarmed after this."""
        self._points.clear()
        self._confirmed = None
        self._state = SelectionState.CANCELLED
        self._message = "Cancelled. Nothing was captured."

    def reset(self) -> None:
        """Return to the initial state, forgetting the purpose as well."""
        self._points.clear()
        self._confirmed = None
        self._purpose = None
        self._tolerance = 0.0
        self._state = SelectionState.IDLE
        self._message = "Point selection is off."

    def confirm(self) -> TwoPointSelection:
        """Commit the previewed pair.

        Raises ``ValueError`` unless two points are captured. For a joint axis this
        is the step that makes the axis exist at all; for a measurement it records
        that the number was read, and both are spelled the same way so that the GUI
        has one path rather than two.
        """
        result = self.result
        if result is None or self._state is not SelectionState.PREVIEW:
            raise ValueError(
                "There is nothing to confirm: two points have not been captured."
            )
        self._confirmed = result
        self._state = SelectionState.COMPLETED
        if result.purpose is SelectionPurpose.JOINT_AXIS:
            origin = _format_point(result.origin, self._unit)
            direction = result.direction
            self._message = (
                f"Joint axis confirmed. Origin {origin}, direction "
                f"({direction[0]:.5f}, {direction[1]:.5f}, {direction[2]:.5f}), "
                f"from a {result.distance:.4f} {self._unit} baseline. The origin is "
                "the midpoint of the two picks, which is the only origin two points "
                "justify -- check it against the part."
            )
        else:
            self._message = (
                f"Measurement recorded: {result.distance:.4f} {self._unit}."
            )
        return result

    def invalidate(self, reason: str) -> bool:
        """Discard the selection because what it referred to has changed.

        Called when the model is replaced or the geometry regenerated. Returns
        whether anything was actually discarded, so the caller can stay quiet when
        there was nothing to lose.

        This is the method whose absence produced the original defect. Coordinates
        picked on one solid are meaningless on the next one, and a controller that
        keeps them will happily pair them across the boundary.
        """
        had_something = self._state is not SelectionState.IDLE or bool(self._points)
        self.reset()
        if had_something:
            self._message = (
                f"The point selection was discarded because {reason}. "
                "Nothing picked earlier applies to the geometry now displayed."
            )
        return had_something

    # -- internals -------------------------------------------------------------

    def _preview_message(self) -> str:
        result = self.result
        assert result is not None  # only called from the PREVIEW transition
        second = _format_point(result.second, self._unit)
        if result.purpose is SelectionPurpose.JOINT_AXIS:
            return (
                f"Second point {second}. Axis preview drawn through the midpoint. "
                "Nothing will use this axis until you confirm it."
            )
        return (
            f"Second point {second}. Distance {result.distance:.4f} {self._unit}. "
            "Clear to measure again."
        )
