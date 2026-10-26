"""Centreline and section-profile reconstruction for a flexure member.

Given a solid and a direction to sweep along, this recovers one centreline per
distinct member -- two, for the A3 twin-strap part -- together with the cross-section
properties at each station. That profile is what the reduced-order beam model
integrates.

Method
------

Two passes, for the reason set out in :mod:`barnes_ui.core.flexure.section`:

1. **Locate.** Cut with planes perpendicular to the sweep axis at regular intervals.
   Group the resulting regions into members by proximity, and take each region's
   centroid as a provisional centreline point. These sections are oblique wherever the
   member is inclined, so their areas and depths are inflated and are used only for
   locating the path, never for stiffness.

2. **Measure.** Differentiate the provisional path to get a tangent at each station,
   then re-cut perpendicular to that tangent. These sections are the true normal
   sections and are the ones reported.

The honest limitation: this works for a member that is single-valued along the sweep
axis -- one section per member per station. A serpentine meander that doubles back is
not single-valued along any straight axis, and for that geometry this routine will
mis-group the regions. It reports when it detects a varying region count rather than
quietly producing a wrong path. Meander support needs path-following rather than
axis-sweeping and is deliberately not faked here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..provenance import (
    CAVEAT_MESH_DERIVED,
    Provenance,
    TaggedValue,
)
from .section import CrossSection, section_solid

logger = logging.getLogger(__name__)

__all__ = ["CenterlineStation", "Member", "extract_members", "CenterlineError"]


class CenterlineError(RuntimeError):
    """Centreline reconstruction could not produce a usable result."""


@dataclass(frozen=True)
class CenterlineStation:
    """One sampled point along a member's centreline."""

    #: Arc length from the start of the member, millimetres.
    s: float
    position: tuple[float, float, float]
    tangent: tuple[float, float, float]
    section: CrossSection

    @property
    def area(self) -> float:
        return self.section.area

    @property
    def i_bending(self) -> float:
        return self.section.i_bending


@dataclass
class Member:
    """One continuous beam-like member recovered from the solid.

    For the A3 twin-strap flexure there are two of these, one per strap.
    """

    index: int
    stations: list[CenterlineStation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def arc_length(self) -> float:
        """Centreline arc length, millimetres."""
        return self.stations[-1].s if self.stations else 0.0

    @property
    def chord_length(self) -> float:
        """Straight-line distance between the member's two ends, millimetres."""
        if len(self.stations) < 2:
            return 0.0
        start = np.asarray(self.stations[0].position)
        end = np.asarray(self.stations[-1].position)
        return float(np.linalg.norm(end - start))

    @property
    def curvature_ratio(self) -> float:
        """Arc length divided by chord length. 1.0 is straight."""
        chord = self.chord_length
        return self.arc_length / chord if chord > 0 else 1.0

    @property
    def mean_area(self) -> float:
        return float(np.mean([st.area for st in self.stations])) if self.stations else 0.0

    @property
    def min_area(self) -> float:
        return float(min(st.area for st in self.stations)) if self.stations else 0.0

    def area_profile(self) -> np.ndarray:
        return np.array([st.area for st in self.stations])

    def inertia_profile(self) -> np.ndarray:
        return np.array([st.i_bending for st in self.stations])

    def arc_coordinates(self) -> np.ndarray:
        return np.array([st.s for st in self.stations])

    def positions(self) -> np.ndarray:
        return np.array([st.position for st in self.stations])

    def tangents(self) -> np.ndarray:
        return np.array([st.tangent for st in self.stations])

    def equivalent_section(self) -> tuple[float, float]:
        """Area-weighted mean equivalent rectangle (width, depth) in millimetres."""
        if not self.stations:
            return (0.0, 0.0)
        rects = np.array([st.section.equivalent_rectangle for st in self.stations])
        return (float(rects[:, 0].mean()), float(rects[:, 1].mean()))

    def tagged_arc_length(self, is_exact: bool) -> TaggedValue:
        """Arc length as a provenance-tagged value.

        Tagged as a geometric measurement for exact B-rep input, carrying the
        mesh-derived caveat otherwise. Note that even for exact input this is a
        *sampled* polyline length, so it slightly understates a smoothly curved path;
        the sampling note is attached by the extractor.
        """
        value = TaggedValue(
            self.arc_length, "mm", Provenance.GEOMETRIC_MEASUREMENT,
            label=f"Member {self.index} centreline arc length",
        )
        return value if is_exact else value.with_caveat(CAVEAT_MESH_DERIVED)


def extract_members(
    shape: Any,
    sweep_axis: Sequence[float],
    bending_axis: Sequence[float],
    start: float,
    end: float,
    samples: int = 60,
    grouping_tolerance: float | None = None,
) -> list[Member]:
    """Recover centrelines and normal-section profiles.

    Parameters
    ----------
    shape:
        The solid to section.
    sweep_axis:
        Direction to sweep the locating cuts along. For a flexure spanning a joint,
        this is the member's general run direction.
    bending_axis:
        The axis bending occurs about -- the joint axis for a finger flexure. Passed
        through to the sectioner so that ``i_bending`` is the relevant second moment.
    start, end:
        Range along ``sweep_axis``, measured as a signed distance from the origin, over
        which to sample. The caller sets these to exclude the attachment features
        (collars, roots), which are not beam-like and must not be in the beam model.
    samples:
        Number of locating stations. 60 is a reasonable default: enough to resolve an
        arch, cheap enough to stay interactive.
    grouping_tolerance:
        Maximum distance between consecutive centroids for them to be treated as the
        same member. Defaults to a generous multiple of the station spacing.

    Raises
    ------
    CenterlineError
        If no sections were found anywhere in the range, or if the member count varies
        across stations -- which means the grouping assumption does not hold for this
        geometry and the result would be meaningless.
    """
    axis = _unit(np.asarray(sweep_axis, dtype=float))
    bending = _unit(np.asarray(bending_axis, dtype=float))

    if samples < 4:
        raise ValueError("At least 4 samples are needed to estimate tangents.")
    if end <= start:
        raise ValueError("end must be greater than start.")

    spacing = (end - start) / (samples - 1)
    if grouping_tolerance is None:
        # Generous: members must be further apart than this to be distinguished, and
        # consecutive points on one member must be closer. For the A3 part the straps
        # are 5.7 mm apart and the stations around 0.5 mm apart, so there is a wide
        # margin either way.
        grouping_tolerance = max(3.0 * abs(spacing), 1.0)

    # --- pass 1: locate -----------------------------------------------------
    located: list[list[CrossSection]] = []
    for i in range(samples):
        offset = start + i * spacing
        found = section_solid(shape, axis * offset, axis, u_hint=bending)
        located.append(found)

    populated = [(i, s) for i, s in enumerate(located) if s]
    if not populated:
        raise CenterlineError(
            "No cross-sections were found anywhere in the requested range. Check the "
            "sweep axis and the start/end limits against the model's bounding box."
        )

    counts = {len(s) for _, s in populated}
    if len(counts) != 1:
        raise CenterlineError(
            f"The number of cross-sections varies along the sweep ({sorted(counts)}). "
            "This routine assumes each member is single-valued along the sweep axis, "
            "which holds for straps and simple arches but not for a serpentine meander "
            "that doubles back. Restrict the range to exclude attachment features, or "
            "use an explicit centreline for this geometry -- path-following extraction "
            "is not implemented."
        )

    member_count = counts.pop()
    tracks = _group_into_tracks(populated, member_count, grouping_tolerance)

    # --- pass 2: measure ----------------------------------------------------
    members: list[Member] = []
    for member_index, track in enumerate(tracks):
        provisional = np.array([section.centroid for _, section in track])
        tangents = _tangents_from_polyline(provisional)

        stations: list[CenterlineStation] = []
        skipped = 0
        for point, tangent in zip(provisional, tangents):
            normal_sections = section_solid(shape, point, tangent, u_hint=bending)
            best = _nearest_section(normal_sections, point)
            if best is None:
                skipped += 1
                continue
            stations.append(
                CenterlineStation(
                    s=0.0,  # filled in below, once the final path is known
                    position=best.centroid,
                    tangent=(float(tangent[0]), float(tangent[1]), float(tangent[2])),
                    section=best,
                )
            )

        if len(stations) < 3:
            raise CenterlineError(
                f"Member {member_index} yielded only {len(stations)} usable normal "
                "sections. The sweep range probably includes geometry that is not "
                "beam-like."
            )

        stations = _assign_arc_length(stations)
        member = Member(index=member_index, stations=stations)
        member.notes.append(
            f"{len(stations)} normal sections over {member.arc_length:.4f} mm of "
            f"centreline (chord {member.chord_length:.4f} mm, "
            f"arc/chord {member.curvature_ratio:.4f})."
        )
        member.notes.append(
            "Arc length is a sampled polyline length and therefore slightly understates "
            "a smoothly curved path; refine the sample count to quantify the effect."
        )
        if skipped:
            member.notes.append(
                f"{skipped} station(s) produced no normal section and were dropped."
            )
        members.append(member)

    return members


def _group_into_tracks(
    populated: list[tuple[int, list[CrossSection]]],
    member_count: int,
    tolerance: float,
) -> list[list[tuple[int, CrossSection]]]:
    """Assign sections at successive stations to continuous members.

    Greedy nearest-neighbour matching against the previous station. Adequate here
    because the members are far apart relative to the station spacing; it would need
    replacing for members that approach or cross one another.
    """
    first_index, first_sections = populated[0]
    tracks: list[list[tuple[int, CrossSection]]] = [
        [(first_index, s)] for s in first_sections
    ]

    for station_index, sections in populated[1:]:
        remaining = list(sections)
        for track in tracks:
            previous = np.asarray(track[-1][1].centroid)
            if not remaining:
                break
            distances = [
                float(np.linalg.norm(np.asarray(s.centroid) - previous))
                for s in remaining
            ]
            best = int(np.argmin(distances))
            if distances[best] <= tolerance:
                track.append((station_index, remaining.pop(best)))
            else:
                logger.debug(
                    "Station %d: nearest region is %.3f mm away, beyond the %.3f mm "
                    "grouping tolerance.", station_index, distances[best], tolerance,
                )

    # Order members by their position along the first station, so member indices are
    # stable between runs rather than depending on the boolean's output order.
    tracks.sort(key=lambda t: t[0][1].centroid)
    return [t for t in tracks if len(t) >= 3][:member_count] or tracks


def _tangents_from_polyline(points: np.ndarray) -> np.ndarray:
    """Unit tangents by central differences, one-sided at the ends."""
    n = len(points)
    tangents = np.zeros_like(points)
    for i in range(n):
        if i == 0:
            delta = points[1] - points[0]
        elif i == n - 1:
            delta = points[-1] - points[-2]
        else:
            delta = points[i + 1] - points[i - 1]
        norm = np.linalg.norm(delta)
        tangents[i] = delta / norm if norm > 1.0e-12 else np.array([1.0, 0.0, 0.0])
    return tangents


def _nearest_section(
    sections: list[CrossSection], point: np.ndarray
) -> CrossSection | None:
    """Pick the section region whose centroid is nearest ``point``.

    A tangent-normal cut through a twin-strap part still intersects both straps, so
    the correct region has to be selected rather than assumed to be the only one or
    the largest one.
    """
    if not sections:
        return None
    distances = [float(np.linalg.norm(np.asarray(s.centroid) - point)) for s in sections]
    return sections[int(np.argmin(distances))]


def _assign_arc_length(stations: list[CenterlineStation]) -> list[CenterlineStation]:
    """Replace placeholder arc coordinates with cumulative path length."""
    positions = np.array([st.position for st in stations])
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(steps)])
    return [
        CenterlineStation(
            s=float(s), position=st.position, tangent=st.tangent, section=st.section
        )
        for s, st in zip(cumulative, stations)
    ]


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm < 1.0e-12:
        raise ValueError("Cannot normalise a zero-length vector.")
    return vector / norm
