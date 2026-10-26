"""Path-following centreline tracing, for members that double back.

Why this exists
---------------

:func:`barnes_ui.core.flexure.extract_members` sweeps cutting planes along a straight
axis. That works for a member which is single-valued along some axis -- a strap, a
simple arch -- and it fails for a serpentine meander, which reverses direction
repeatedly and is single-valued along no straight axis at all.

The failure is worse than an error. Run on a generated 4-run meander whose true section
is 1.0 x 1.2 mm, the axis sweep returned **no error** and reported a section area
overstated by 3.1x, a second moment overstated by 4x, and an arc length of 1.61 mm
against a true centreline of 62.14 mm. Every number looked like a number. This is risk
R1 in the register -- a plausible-looking physically wrong result -- caught only because
the meander was generated with analytically known properties to compare against.

The cause is that at a given station, a plane normal to the sweep axis cuts the straight
run *and* part of the adjacent turn, and because the two are fused into one body the
intersection comes back as a single connected region: a long sliver spanning most of
the part rather than a strap cross-section. The region count never varies, so the guard
in ``extract_members`` never fires.

Method
------

Predictor-corrector marching along the member instead of sweeping across it:

1. At the current point with the current tangent, cut a plane normal to that tangent.
2. Pick the region nearest the current point and take its centroid. That *corrects* the
   point onto the true centreline.
3. Step forward along the tangent by a fraction of the section size.
4. Cut again, correct again, and take the new tangent from the displacement between
   consecutive corrected centroids.

Because the plane is always normal to the local tangent, the section is a true normal
section at a turn just as on a straight run: the tangent there is circumferential, so
the plane is radial and cuts the annulus in a clean width-by-thickness rectangle.

Guards
------

Marching can still go wrong -- at a turn the plane may clip an adjacent run, and at a
turn tight relative to the section depth a normal section stops being well defined. So
each section's area is compared against the running median and an outlier stops the
trace with an explanation rather than being absorbed into the profile.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np

from .centerline import CenterlineStation, Member
from .section import CrossSection, section_solid

logger = logging.getLogger(__name__)

__all__ = ["trace_centerline", "TraceError", "seed_from_extreme_point"]


class TraceError(RuntimeError):
    """Centreline tracing could not complete."""


def trace_centerline(
    shape: Any,
    seed_point: Sequence[float],
    seed_direction: Sequence[float],
    bending_axis: Sequence[float],
    step: float | None = None,
    max_steps: int = 20000,
    area_tolerance: float = 2.0,
    continuity_factor: float = 2.0,
    index: int = 0,
) -> Member:
    """Trace one member's centreline by marching along it.

    Parameters
    ----------
    shape:
        The solid to trace through.
    seed_point:
        A point on or very near the member's centreline, at the end to start from.
    seed_direction:
        Direction to march in from the seed.
    bending_axis:
        Axis bending occurs about, passed to the sectioner so that ``i_bending`` is the
        relevant second moment.
    step:
        Marching step in mm. Defaults to a quarter of the smaller section dimension,
        measured from the first section, which adapts automatically between a 1 mm
        flexure and a 20 mm member.
    max_steps:
        Safety limit. Hitting it raises, because a trace that does not terminate has
        gone somewhere unintended and its output should not be used.
    area_tolerance:
        A section whose area exceeds this multiple of the running median -- or falls
        below its reciprocal -- stops the trace. Catches the plane clipping an adjacent
        run, which is the failure mode that made the axis sweep produce nonsense.
    continuity_factor:
        Largest permitted advance, as a multiple of ``step``. Stops the march jumping
        to a neighbouring run when the plane passes the end of the current one.

    Raises
    ------
    TraceError
        If the seed is not on the solid, if no progress can be made, or if the step
        limit is reached.
    """
    point = np.asarray(seed_point, dtype=float)
    tangent = _unit(np.asarray(seed_direction, dtype=float))
    bending = _unit(np.asarray(bending_axis, dtype=float))

    first = _section_at(shape, point, tangent, bending)
    if first is None:
        raise TraceError(
            f"No cross-section at the seed point {tuple(point)} in direction "
            f"{tuple(tangent)}. The seed must lie on the member; if it sits exactly on "
            "an end face, move it a little way inside."
        )

    if step is None:
        step = max(0.25 * min(first.width_u, first.width_v), 1.0e-3)
        logger.debug("Trace step auto-set to %.4f mm from the first section.", step)

    stations: list[tuple[np.ndarray, np.ndarray, CrossSection]] = []
    areas: list[float] = []

    current_point = np.asarray(first.centroid, dtype=float)
    current_tangent = tangent
    current_section = first
    notes: list[str] = []

    for iteration in range(max_steps):
        stations.append((current_point.copy(), current_tangent.copy(), current_section))
        areas.append(current_section.area)

        predicted = current_point + step * current_tangent
        nxt = _section_at(shape, predicted, current_tangent, bending)

        if nxt is None:
            notes.append(
                f"Trace ended after {len(stations)} stations: the section plane left "
                "the solid, which is the expected way to reach the end of a member."
            )
            break

        next_point = np.asarray(nxt.centroid, dtype=float)
        advance = next_point - current_point
        distance = float(np.linalg.norm(advance))

        if distance < 1.0e-9:
            raise TraceError(
                f"Tracing stalled at {tuple(current_point)} after {len(stations)} "
                "stations: the corrected centroid did not move. Try a larger step."
            )

        # Continuity. The corrected centroid lies in a plane one step away, so a
        # well-behaved advance is barely more than the step itself. A much larger jump
        # means the nearest region belonged to a different part of the member.
        #
        # This is what happens at the far end: once the plane passes the last run's end
        # face, the nearest remaining region is the neighbouring run, and the march
        # jumps straight to it. On the test meander that produced a single 3.0133 mm
        # step -- exactly one pitch -- at station 308 of 310, which travelled 28.8 mm
        # backwards along the true centreline and inflated the reported arc length.
        # The area check caught it only one station later, by which time the bad
        # station was already in the profile.
        if distance > continuity_factor * step:
            notes.append(
                f"Trace stopped after {len(stations)} stations: the next centroid is "
                f"{distance:.4f} mm away, more than {continuity_factor:g}x the "
                f"{step:.4f} mm step. The march would have jumped to a different part "
                "of the member, which is how a trace reaches the end of a run that has "
                "a neighbour alongside it. The traced portion up to this point is "
                "reported; the remainder is not."
            )
            break

        # Outlier rejection. Compared against the median rather than the mean so a
        # single bad section cannot drag the reference along with it.
        median_area = float(np.median(areas))
        ratio = nxt.area / median_area if median_area > 0 else 1.0
        if ratio > area_tolerance or ratio < 1.0 / area_tolerance:
            notes.append(
                f"Trace stopped after {len(stations)} stations: the next section's "
                f"area ({nxt.area:.4f} mm^2) is {ratio:.2f}x the running median "
                f"({median_area:.4f} mm^2). The cutting plane is most likely clipping "
                "an adjacent part of the member, which happens where a turn is tight "
                "relative to the section depth. The traced portion up to this point is "
                "reported; the remainder is not."
            )
            break

        # A reversal means the march has turned back on itself, which is not curvature
        # but a tracking failure -- real curvature changes the tangent gradually.
        new_tangent = advance / distance
        if float(np.dot(new_tangent, current_tangent)) < -0.5:
            notes.append(
                f"Trace stopped after {len(stations)} stations: the marching direction "
                "reversed, so tracking was lost. Reduce the step size."
            )
            break

        current_point = next_point
        current_tangent = new_tangent
        current_section = nxt
    else:
        raise TraceError(
            f"Tracing did not terminate within {max_steps} steps. Either the step is "
            "far too small for the member, or the march is circulating. No result is "
            "returned, because a trace that does not terminate has gone somewhere "
            "unintended."
        )

    if len(stations) < 3:
        raise TraceError(
            f"Only {len(stations)} station(s) were traced, which is too few to form a "
            "centreline. Check the seed point and direction."
        )

    member = _build_member(stations, index)
    member.notes.extend(notes)
    member.notes.append(
        f"Traced by path-following with a {step:.4f} mm step; "
        f"{len(stations)} stations over {member.arc_length:.4f} mm."
    )
    member.notes.append(
        "Arc length is a sampled polyline through the section centroids and therefore "
        "slightly understates a smoothly curved path. It also excludes up to one step "
        "at each end, where the section plane leaves the solid."
    )
    return member


def _section_at(
    shape: Any, point: np.ndarray, tangent: np.ndarray, bending: np.ndarray
) -> CrossSection | None:
    """Normal section at a point, choosing the region nearest that point."""
    try:
        sections = section_solid(shape, point, tangent, u_hint=bending)
    except Exception as exc:  # pragma: no cover - boolean failure at an awkward spot
        logger.debug("Section failed at %s: %s", tuple(point), exc)
        return None
    if not sections:
        return None
    distances = [
        float(np.linalg.norm(np.asarray(s.centroid) - point)) for s in sections
    ]
    return sections[int(np.argmin(distances))]


def _build_member(
    stations: list[tuple[np.ndarray, np.ndarray, CrossSection]], index: int
) -> Member:
    positions = np.array([s[0] for s in stations])
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(steps)])

    built = [
        CenterlineStation(
            s=float(arc[i]),
            position=tuple(float(v) for v in stations[i][0]),
            tangent=tuple(float(v) for v in stations[i][1]),
            section=stations[i][2],
        )
        for i in range(len(stations))
    ]
    return Member(index=index, stations=built)


def seed_from_extreme_point(
    shape: Any, along: Sequence[float], inset: float = 0.5
) -> tuple[np.ndarray, np.ndarray]:
    """Find a starting point at the extreme end of a shape along a direction.

    Returns ``(point, direction)`` ready to pass to :func:`trace_centerline`. The point
    is inset from the extreme face, because a plane lying exactly on an end face cuts a
    degenerate section.

    Convenience only: for anything ambiguous the user should pick the start face in the
    viewport, which is what Phase 4's attachment-region selection provides.
    """
    from ..cad.inspect import bounding_box

    direction = _unit(np.asarray(along, dtype=float))
    box = bounding_box(shape)
    lo = np.array([box.xmin, box.ymin, box.zmin])
    hi = np.array([box.xmax, box.ymax, box.zmax])
    centre = 0.5 * (lo + hi)

    # Start at the minimum end along the direction, at the centre of the other two axes.
    extreme = np.where(direction > 0, lo, hi)
    point = np.where(np.abs(direction) > 1.0e-9, extreme, centre)
    return point + inset * direction, direction


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm < 1.0e-12:
        raise ValueError("Cannot normalise a zero-length vector.")
    return vector / norm
