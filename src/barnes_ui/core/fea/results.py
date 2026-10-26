"""Parsing CalculiX output.

Two files matter. The ``.dat`` file carries the printed reaction forces that the
torque-angle workflow depends on, and the ``.frd`` file carries the nodal fields for
visualisation.

Convergence is parsed from the solver log and travels with the result, because the
project's rule is that convergence status is part of the answer rather than a detail of
how it was obtained. A result object that cannot say whether its increments converged
is not usable, and :attr:`FeaResult.is_trustworthy` is false for one that did not.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..provenance import Caveat, Provenance, TaggedValue

logger = logging.getLogger(__name__)

__all__ = [
    "ConvergenceReport",
    "FeaResult",
    "parse_dat_reactions",
    "parse_frd_displacements",
    "parse_convergence",
    "CAVEAT_NOT_CONVERGED",
    "CAVEAT_NO_MESH_STUDY",
]


CAVEAT_NOT_CONVERGED = Caveat(
    "not_converged",
    "The solver did not converge on every increment. This result is not usable as a "
    "prediction.",
)
CAVEAT_NO_MESH_STUDY = Caveat(
    "no_mesh_study",
    "No mesh-convergence study accompanies this result, so its discretisation error is "
    "unknown. A single mesh cannot tell you how far from the converged answer it is.",
)


@dataclass
class ConvergenceReport:
    """What the solver log says about how the solution went."""

    converged: bool
    increments_attempted: int = 0
    increments_completed: int = 0
    cutbacks: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_tail: str = ""

    @property
    def summary(self) -> str:
        if self.converged:
            text = (
                f"Converged in {self.increments_completed} increment(s)"
                + (f" with {self.cutbacks} cutback(s)" if self.cutbacks else "")
            )
        else:
            text = (
                f"DID NOT CONVERGE after {self.increments_completed} of "
                f"{self.increments_attempted} increment(s)"
            )
        if self.warnings:
            text += f"; {len(self.warnings)} solver warning(s)"
        return text


@dataclass
class FeaResult:
    """The outcome of one finite element run.

    Carries its own convergence status on purpose. A caller cannot obtain the numbers
    without also being handed the statement of whether the solve worked.
    """

    convergence: ConvergenceReport
    #: Total reaction force per node set, N, keyed by set name.
    reaction_forces: dict[str, np.ndarray] = field(default_factory=dict)
    #: Total reaction moment about a stated point, N.mm, keyed by set name.
    reaction_moments: dict[str, np.ndarray] = field(default_factory=dict)
    #: Nodal displacements, (N, 3) in mm.
    displacements: np.ndarray | None = None
    run_directory: Path | None = None
    mesh_description: str = ""
    material_provenance: Provenance = Provenance.UNVALIDATED_ASSUMPTION
    material_caveats: tuple[Caveat, ...] = ()
    mesh_study_performed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_trustworthy(self) -> bool:
        """Whether this result may be quoted as a prediction at all."""
        return self.convergence.converged

    def caveats(self) -> tuple[Caveat, ...]:
        caveats = tuple(self.material_caveats)
        if not self.convergence.converged:
            caveats = caveats + (CAVEAT_NOT_CONVERGED,)
        if not self.mesh_study_performed:
            caveats = caveats + (CAVEAT_NO_MESH_STUDY,)
        return caveats

    def tagged_moment(self, node_set: str, axis: np.ndarray) -> TaggedValue:
        """Reaction moment about an axis as a provenance-tagged value.

        Raises if the run did not converge. A non-converged solve has no result to
        report, and returning one with a caveat attached would leave a number on screen
        for somebody to read.
        """
        if not self.convergence.converged:
            raise ValueError(
                "This run did not converge, so it has no reaction moment to report. "
                f"{self.convergence.summary}"
            )
        moment = self.reaction_moments.get(node_set)
        if moment is None:
            raise KeyError(
                f"No reaction moment was recorded for node set {node_set!r}. Available: "
                f"{sorted(self.reaction_moments)}"
            )
        direction = np.asarray(axis, dtype=float)
        direction = direction / np.linalg.norm(direction)
        # An FEA result is never stronger than the material it was computed with.
        provenance = min(self.material_provenance, Provenance.FEA_RESULT)
        return TaggedValue(
            float(np.dot(moment, direction)), "N.mm", provenance,
            caveats=self.caveats(), label=f"Reaction moment on {node_set}",
        )


def parse_convergence(log_text: str) -> ConvergenceReport:
    """Read convergence status out of the CalculiX log.

    CalculiX does not emit a single machine-readable status line, so this works from
    the increment accounting and the error text. When the picture is ambiguous the
    result is reported as *not* converged, because the cost of wrongly trusting a bad
    solve is far higher than the cost of re-running a good one.
    """
    attempted = len(re.findall(r"increment\s+(\d+)", log_text, re.IGNORECASE))
    completed = len(re.findall(r"convergence", log_text, re.IGNORECASE))
    cutbacks = len(
        re.findall(r"divergence|cutback|decreasing the increment", log_text, re.IGNORECASE)
    )

    errors = [
        line.strip() for line in log_text.splitlines()
        if re.search(r"\*ERROR|error\b", line, re.IGNORECASE)
    ]
    warnings = [
        line.strip() for line in log_text.splitlines()
        if re.search(r"\*WARNING", line, re.IGNORECASE)
    ]

    finished_cleanly = bool(
        re.search(r"Job finished", log_text, re.IGNORECASE)
    )
    converged = finished_cleanly and not errors

    return ConvergenceReport(
        converged=converged,
        increments_attempted=attempted,
        increments_completed=completed,
        cutbacks=cutbacks,
        warnings=warnings[:50],
        errors=errors[:50],
        raw_tail="\n".join(log_text.splitlines()[-40:]),
    )


def parse_dat_reactions(path: Path | str) -> dict[str, np.ndarray]:
    """Read ``total force`` blocks from a CalculiX ``.dat`` file.

    With ``*NODE PRINT, TOTALS=ONLY`` CalculiX writes a header naming the set followed
    by the summed force components. The format is positional rather than labelled, so
    this is a tolerant parse that takes the last three floats on the data line.
    """
    path = Path(path)
    if not path.is_file():
        return {}

    text = path.read_text(encoding="utf-8", errors="replace")
    reactions: dict[str, np.ndarray] = {}

    pattern = re.compile(
        r"total force \(fx,fy,fz\) for set ([A-Za-z0-9_]+)[^\n]*\n\s*\n?\s*"
        r"([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        name = match.group(1)
        try:
            reactions[name] = np.array(
                [float(match.group(2)), float(match.group(3)), float(match.group(4))]
            )
        except ValueError:  # pragma: no cover - malformed numeric field
            logger.warning("Could not parse a reaction block for set %s", name)

    if not reactions:
        logger.info("No total-force blocks found in %s", path)
    return reactions


def parse_frd_displacements(path: Path | str) -> np.ndarray | None:
    """Read the final displacement field from a ``.frd`` file.

    The ``.frd`` format is fixed-width and block structured. This reads the last
    displacement block, which corresponds to the final increment. Returns ``None``
    when none is present, which happens when the run failed before writing results.
    """
    path = Path(path)
    if not path.is_file():
        return None

    rows: list[tuple[int, float, float, float]] = []
    in_block = False

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "DISP" in line and line.strip().startswith("-4"):
                rows.clear()      # a later block supersedes an earlier one
                in_block = True
                continue
            if not in_block:
                continue
            if line.startswith(" -3"):
                in_block = False
                continue
            if line.startswith(" -1"):
                try:
                    node = int(line[3:13])
                    ux = float(line[13:25])
                    uy = float(line[25:37])
                    uz = float(line[37:49])
                    rows.append((node, ux, uy, uz))
                except (ValueError, IndexError):
                    continue

    if not rows:
        return None

    rows.sort(key=lambda r: r[0])
    return np.array([[r[1], r[2], r[3]] for r in rows], dtype=float)


def moment_about(
    reaction_force: np.ndarray,
    application_point: np.ndarray,
    about_point: np.ndarray,
) -> np.ndarray:
    """Moment of a resultant force about a point, N.mm.

    Only valid for a resultant acting at a single point. For a distributed reaction over
    a node set the moment must be summed per node, which requires per-node forces rather
    than the set total -- hence the rigid-body reference-node approach in the deck
    generator, which concentrates the reaction at one node where this is exact.
    """
    lever = np.asarray(application_point, dtype=float) - np.asarray(about_point, dtype=float)
    return np.cross(lever, np.asarray(reaction_force, dtype=float))
