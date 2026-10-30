"""Rotational stiffness of a flexure joint, measured by nonlinear FEA.

The whole Phase 3 pipeline behind one call: mesh the solid, tie each attachment
region, drive one of them through a small rotation about the joint axis, and read the
reaction moment back.

Why this is in ``core`` rather than in a script
------------------------------------------------

It was in a script first, and then in a second script, and then the GUI wanted it
too. Three copies of a boundary-condition recipe that took two wrong answers to get
right is three chances to fix only one of them. The recipe lives here; the script and
the panel both call it.

The recipe, and the two wrong answers it is built from
-------------------------------------------------------

One attachment region is fully fixed. The other is tied into a rigid body whose
reference node sits on the joint axis, and that reference node is rotated. Dividing
the reported reaction moment by the angle gives the rotational stiffness.

Both earlier mistakes produced converged, warning-free, plausible-looking runs:

* Tying **one** surface of an attachment region rather than all of them. The rest of
  the collar stays free, so the "rigid" body is a single patch dragging a deformable
  shell. The A3 flexure came out 63 times softer than the beam model.
* Leaving the reference node's **translations** free. The collar drifts sideways
  instead of rotating about the axis, giving 55 times. The reaction history was
  perfectly linear and the only symptom was 356 convergence cutbacks.

So every surface inside the attachment depth is tied, and the reference node is
pinned by default. Neither is optional here.

The rotation node's two off-axis rotations are held at zero too, for an
axis-aligned joint direction: the joint is a hinge. Leaving them free was not a wrong
answer but a badly conditioned one -- on the A8 meander strip it cut the first
increment back to ~0.01 deg, with the largest residual on the free DOF 3.

What it does not decide
-----------------------

The joint axis. ``axis_point`` has **no default**, and that is the result of a real
mistake rather than caution.

An earlier version of this code defaulted it to the centre of the part's bounding
box. On the A3 twin strap that puts the axis at z = 7.42 mm, because the arch bulges
upward and drags the box with it, while the run the project's documented
6.103 N.mm/rad came from used z = 5.44 mm -- the centroid of the mounting features on
the collars, which is where the joint physically is. Nobody noticed, because both
numbers are plausible and the run converged either way.

So the axis is a required argument. :func:`suggest_axis_point` offers the bounding
box centre for a caller that wants somewhere to start, and it is named "suggest"
because that is all it is. Risk R4.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..cad.inspect import bounding_box
from ..material.models import HyperelasticModel
from ..provenance import Provenance, TaggedValue
from .deck import BoundaryCondition, DeckSettings, RigidBody, write_deck
from .meshing import Mesh, MeshSettings, generate_mesh
from .results import FeaResult
from .runner import run_analysis
from .solver import SolverInfo

logger = logging.getLogger(__name__)

__all__ = [
    "JointStiffnessSetup",
    "suggest_axis_point",
    "JointStiffnessResult",
    "JointStiffnessError",
    "classify_attachment_surfaces",
    "measure_joint_stiffness",
]


class JointStiffnessError(RuntimeError):
    """The analysis could not be set up."""


def suggest_axis_point(shape: Any) -> tuple[float, float, float]:
    """The centre of a shape's bounding box, offered as a starting point.

    A suggestion and nothing more. On a flexure whose straps arch away from the
    joint, the arch drags the bounding box with it and this sits a millimetre or two
    off the real axis -- on the A3 part, two millimetres, which is enough to change
    the reported stiffness substantially. Look at it in the viewport, and prefer a
    point derived from the mounting features where there are any.
    """
    box = bounding_box(shape)
    return tuple(float(c) for c in box.centre)


@dataclass(frozen=True)
class JointStiffnessSetup:
    """Everything that defines the analysis except the geometry and the material."""

    #: Depth of each attachment region, measured along ``span_axis``, in mm.
    attachment_depth: float

    #: A point on the joint axis, in mm. Required, deliberately -- see the module
    #: docstring for the two-millimetre mistake that made it so.
    axis_point: tuple[float, float, float]

    #: Prescribed rotation, in degrees.
    #:
    #: Small by default. The reduced-order model this is usually compared against is
    #: a tangent stiffness at the neutral position and linear by construction, so a
    #: large angle would conflate the beam idealisation with the linear-kinematics
    #: extrapolation. Two degrees keeps both models inside their own regime.
    rotation_deg: float = 2.0

    #: Which coordinate axis the part spans between its attachments: 0=X, 1=Y, 2=Z.
    span_axis: int = 1

    #: Joint axis direction. Must not be parallel to ``span_axis``.
    joint_direction: tuple[float, float, float] = (1.0, 0.0, 0.0)

    #: The part's thinnest feature, in mm. Required when it is interior: the default
    #: element size comes from the bounding box's smallest extent, which on the A3
    #: twin strap is 10.95 mm against a 1.0 mm strap, and CalculiX rejected that mesh.
    smallest_feature: float | None = None

    #: Explicit element size in mm, overriding the through-thickness count.
    element_size: float | None = None
    elements_through_thickness: int = 2
    second_order: bool = True

    def __post_init__(self) -> None:
        if self.attachment_depth <= 0.0:
            raise JointStiffnessError("attachment_depth must be positive.")
        if self.span_axis not in (0, 1, 2):
            raise JointStiffnessError(
                f"span_axis must be 0, 1 or 2, got {self.span_axis}."
            )
        if self.rotation_deg == 0.0:
            raise JointStiffnessError(
                "A zero rotation produces a converged null solve: every reaction "
                "exactly zero, reported as success."
            )
        direction = np.asarray(self.joint_direction, dtype=float)
        if np.linalg.norm(direction) < 1.0e-12:
            raise JointStiffnessError("joint_direction is a zero vector.")

    @property
    def rotation_rad(self) -> float:
        return math.radians(self.rotation_deg)

    @property
    def axis_component(self) -> int:
        """Which reaction component is the moment about the joint axis.

        Only meaningful for an axis-aligned joint direction, which is the case this
        reads a single component for; anything else is projected instead.
        """
        direction = np.abs(np.asarray(self.joint_direction, dtype=float))
        return int(np.argmax(direction))


@dataclass
class JointStiffnessResult:
    """What one measurement produced, successful or not."""

    setup: JointStiffnessSetup
    mesh: Mesh
    result: FeaResult
    axis_point: tuple[float, float, float]
    proximal_sets: tuple[str, ...]
    distal_sets: tuple[str, ...]
    torque: float | None = None
    stiffness: float | None = None
    failure: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.stiffness is not None

    def tagged_stiffness(self) -> TaggedValue:
        """The stiffness as a tagged value, or a refusal.

        Raises rather than returning a caveated number for a run that failed. A
        number on screen gets read; a caveat beside it often does not.
        """
        if self.stiffness is None:
            raise JointStiffnessError(
                f"This run produced no usable stiffness. {self.failure}"
            )
        provenance = min(self.result.material_provenance, Provenance.FEA_RESULT)
        return TaggedValue(
            value=self.stiffness,
            unit="N.mm/rad",
            provenance=provenance,
            caveats=self.result.caveats(),
            label=f"joint rotational stiffness at {self.setup.rotation_deg:g} deg",
        )

    def summary(self) -> str:
        lines = [
            self.mesh.describe(),
            f"{len(self.proximal_sets)} proximal and {len(self.distal_sets)} distal "
            "surface set(s) tied.",
            self.result.convergence.summary,
        ]
        if self.stiffness is None:
            lines.append(f"NO RESULT: {self.failure}")
        else:
            lines.append(
                f"reaction moment {self.torque:.6g} N.mm at "
                f"{self.setup.rotation_deg:g} deg"
            )
            lines.append(f"rotational stiffness {self.stiffness:.6g} N.mm/rad")
        lines.extend(self.notes)
        return "\n".join(lines)


def classify_attachment_surfaces(
    mesh: Mesh, span_axis: int, proximal_limit: float, distal_limit: float
) -> tuple[list[str], list[str]]:
    """Split the mesh's surface sets into the two attachment regions.

    A surface counts as proximal only if *every* one of its nodes lies within the
    proximal region, and likewise for distal. A surface straddling a boundary belongs
    to neither and is left free, which is the right treatment for a strap root.
    """
    proximal: list[str] = []
    distal: list[str] = []
    for name, indices in mesh.node_sets.items():
        coordinate = mesh.nodes[np.asarray(indices), span_axis]
        if coordinate.max() <= proximal_limit:
            proximal.append(name)
        elif coordinate.min() >= distal_limit:
            distal.append(name)
    return sorted(proximal), sorted(distal)


def measure_joint_stiffness(
    shape: Any,
    material: HyperelasticModel,
    setup: JointStiffnessSetup,
    solver: SolverInfo | None,
    archive_directory: Path | str | None = None,
    timeout: float = 14400.0,
    progress: Callable[[float, str], None] | None = None,
    cancellation: Any = None,
    title: str = "Joint rotational stiffness",
) -> JointStiffnessResult:
    """Mesh, submit and read back one joint-stiffness measurement.

    Raises :class:`~barnes_ui.core.fea.solver.SolverNotAvailableError` when there is
    no solver. It never substitutes the reduced-order model, which is Phase 3
    criterion 6.
    """
    box = bounding_box(shape)
    low = (box.xmin, box.ymin, box.zmin)[setup.span_axis]
    high = (box.xmax, box.ymax, box.zmax)[setup.span_axis]

    proximal_limit = low + setup.attachment_depth
    distal_limit = high - setup.attachment_depth
    if proximal_limit >= distal_limit:
        raise JointStiffnessError(
            f"Two {setup.attachment_depth:g} mm attachment regions overlap in a part "
            f"only {high - low:.2f} mm long along axis {setup.span_axis}. Reduce the "
            "depth, or check that span_axis names the direction the part actually "
            "spans."
        )

    axis_point = setup.axis_point

    if progress:
        progress(0.05, "Meshing...")
    mesh = generate_mesh(
        shape,
        MeshSettings(
            element_size=setup.element_size,
            elements_through_thickness=setup.elements_through_thickness,
            second_order=setup.second_order,
        ),
        smallest_dimension=setup.smallest_feature,
    )

    proximal, distal = classify_attachment_surfaces(
        mesh, setup.span_axis, proximal_limit, distal_limit
    )
    if not proximal or not distal:
        raise JointStiffnessError(
            f"Found {len(proximal)} proximal and {len(distal)} distal surface set(s); "
            "both must be non-empty. Either the attachment depth does not reach a "
            "complete surface, or span_axis is wrong."
        )

    rigid = RigidBody(
        node_sets=distal,
        reference_point=tuple(float(c) for c in axis_point),
        name="distal",
        pin_reference=True,
    )
    settings = DeckSettings(
        nlgeom=True,
        rigid_bodies=[rigid],
        reaction_sets=[rigid.rotation_set_name, rigid.reference_set_name],
    )
    boundary = [
        BoundaryCondition(name, (1, 2, 3), 0.0, "proximal attachment fixed")
        for name in proximal
    ]
    # DOFs 1-3 on a rigid body's rotation node are rotations about X, Y and Z.
    boundary.append(
        BoundaryCondition(
            rigid.rotation_set_name,
            (setup.axis_component + 1,),
            setup.rotation_rad,
            f"prescribed joint rotation {setup.rotation_deg:g} deg",
        )
    )
    # A PIP joint is a hinge: the distal body turns about the joint axis and nothing
    # else. Left free, the two off-axis rotations are a near-singular mode of the
    # rigid body; on the A8 meander strip the largest residual sat on DOF 3 of this
    # node and the first increment was cut back to ~0.01 deg. Held, it converged in
    # one increment per tenth of the step. Only expressible as per-DOF zeros when the
    # joint axis is a coordinate axis.
    direction = np.asarray(setup.joint_direction, dtype=float)
    if np.count_nonzero(np.abs(direction) > 1.0e-12) == 1:
        boundary.append(
            BoundaryCondition(
                rigid.rotation_set_name,
                tuple(d + 1 for d in range(3) if d != setup.axis_component),
                0.0,
                "hinge: off-axis rotations held",
            )
        )

    deck = write_deck(mesh, material, boundary, settings, title=title)

    if progress:
        progress(0.15, "Submitting to CalculiX...")
    fea = run_analysis(
        deck, mesh, material, solver,
        archive_directory=archive_directory,
        timeout=timeout,
        progress=progress,
        cancellation=cancellation,
    )

    outcome = JointStiffnessResult(
        setup=setup,
        mesh=mesh,
        result=fea,
        axis_point=tuple(float(c) for c in axis_point),
        proximal_sets=tuple(proximal),
        distal_sets=tuple(distal),
    )

    if not fea.is_trustworthy:
        outcome.failure = (
            "The solve is not trustworthy: "
            + (
                "it converged on a null problem, with every displacement and "
                "reaction exactly zero."
                if fea.is_null_solution else fea.convergence.summary
            )
        )
        return outcome

    if not fea.has_reaction(rigid.rotation_set_name):
        outcome.failure = (
            f"No reaction was reported for {rigid.rotation_set_name!r}. Reported: "
            f"{sorted(fea.reaction_forces)}."
        )
        return outcome

    reaction = fea.reaction(rigid.rotation_set_name)
    outcome.torque = float(reaction[setup.axis_component])
    outcome.stiffness = outcome.torque / setup.rotation_rad

    if fea.convergence.cutbacks > 5 * max(1, fea.convergence.increments_completed):
        outcome.notes.append(
            f"{fea.convergence.cutbacks} cutbacks across "
            f"{fea.convergence.increments_completed} increments. A cutback count "
            "far above the increment count has previously been the only visible "
            "symptom of a badly posed boundary condition, so check the setup before "
            "quoting this."
        )
    return outcome
