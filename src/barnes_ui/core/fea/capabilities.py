"""Which advanced solver capabilities have actually been demonstrated here.

Phase 6 criterion 2: *no capability is enabled in the UI until it has passed its
benchmark.* This module is the mechanism. It is not documentation of intent; it is the
gate the application asks before offering a feature.

Why a file on disk rather than a constant in the source
--------------------------------------------------------

"CalculiX supports contact" is a statement about CalculiX. "Contact converges on this
geometry, with this solver build, on this machine" is the statement that matters, and
it is not knowable from source code. A capability therefore becomes available only
when a benchmark has been run *here* and its evidence recorded -- element counts,
measured against expected, convergence record, run archive.

The registry is written by ``scripts/phase6_benchmarks.py`` and read by the GUI and by
any analysis that needs a capability. A fresh checkout starts with everything
``NOT_TESTED``, which disables the features rather than enabling them optimistically.
That asymmetry is the point.

Three statuses, three different meanings
-----------------------------------------

``PASSED`` means a benchmark with a known answer was reproduced within tolerance.
``FAILED`` means it was run and did not reproduce it -- a useful, publishable result
that Phase 6 explicitly permits. ``NOT_AVAILABLE`` means the solver does not have the
feature at all, which is a different thing from it not working: no amount of
re-running will change it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "Capability",
    "CapabilityStatus",
    "CapabilityRecord",
    "CapabilityRegistry",
    "CapabilityNotAvailableError",
    "default_registry_path",
]


class Capability(Enum):
    """An advanced solver feature that Phase 6 investigates."""

    GRAVITY = "gravity"
    TENDON_LOAD = "tendon_load"
    CONTACT_FRICTIONLESS = "contact_frictionless"
    CONTACT_FRICTION = "contact_friction"
    SELF_CONTACT = "self_contact"
    MECHANICAL_STOPS = "mechanical_stops"
    VISCOELASTICITY = "viscoelasticity"

    @property
    def label(self) -> str:
        return {
            Capability.GRAVITY: "Gravity (body load)",
            Capability.TENDON_LOAD: "Tendon load (concentrated force)",
            Capability.CONTACT_FRICTIONLESS: "Frictionless contact",
            Capability.CONTACT_FRICTION: "Contact with Coulomb friction",
            Capability.SELF_CONTACT: "Self-contact",
            Capability.MECHANICAL_STOPS: "Mechanical stops and joint limits",
            Capability.VISCOELASTICITY: "Viscoelastic material behaviour",
        }[self]

    @property
    def benchmark_description(self) -> str:
        """What a passing benchmark for this capability has to show."""
        return {
            Capability.GRAVITY:
                "A cantilever under its own weight matches the closed-form tip "
                "deflection q L^4 / (8 E I) to better than 5 %. Tests the density "
                "path, the *DLOAD path and the tonne/mm^3 unit system at once.",
            Capability.TENDON_LOAD:
                "A concentrated load on a node set produces a reaction equal and "
                "opposite to the applied resultant, to better than 0.5 %.",
            Capability.CONTACT_FRICTIONLESS:
                "A block pressed onto a foundation transmits its full load through "
                "the interface, to better than 2 %, with penetration under 5 % of an "
                "element.",
            Capability.CONTACT_FRICTION:
                "A block under normal load, pushed tangentially below mu*N, does not "
                "slide; the tangential reaction equals the applied shear.",
            Capability.SELF_CONTACT:
                "A strip bent until opposite faces meet shows no interpenetration "
                "and a converged solution.",
            Capability.MECHANICAL_STOPS:
                "A rotation driven past a modelled stop produces a sharp torque rise "
                "at the stop angle and no penetration of the stop.",
            Capability.VISCOELASTICITY:
                "A relaxation test reproduces a Prony-series decay. Requires solver "
                "support, which CalculiX does not have.",
        }[self]


class CapabilityStatus(Enum):
    """How far a capability has got."""

    NOT_TESTED = "not_tested"
    PASSED = "passed"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"

    @property
    def usable(self) -> bool:
        return self is CapabilityStatus.PASSED

    @property
    def label(self) -> str:
        return {
            CapabilityStatus.NOT_TESTED: "Not tested",
            CapabilityStatus.PASSED: "Benchmark passed",
            CapabilityStatus.FAILED: "Benchmark failed",
            CapabilityStatus.NOT_AVAILABLE: "Not available in this solver",
        }[self]


class CapabilityNotAvailableError(RuntimeError):
    """An analysis asked for a capability that has not been demonstrated."""


@dataclass
class CapabilityRecord:
    """The evidence for or against one capability."""

    capability: Capability
    status: CapabilityStatus
    #: What was measured and what it was compared with, in words.
    evidence: str = ""
    measured: float | None = None
    expected: float | None = None
    tolerance: float | None = None
    #: Convergence record: increments, cutbacks, warnings.
    convergence: str = ""
    #: Where the run was archived, so the deck and log can be inspected.
    run_directory: str | None = None
    solver_version: str = ""
    recorded_at: str = ""

    @property
    def relative_error(self) -> float | None:
        if self.measured is None or self.expected in (None, 0.0):
            return None
        return (self.measured - self.expected) / self.expected

    def summary(self) -> str:
        lines = [f"{self.capability.label}: {self.status.label}"]
        if self.relative_error is not None:
            lines.append(
                f"  measured {self.measured:.6g} against {self.expected:.6g} "
                f"({self.relative_error * 100:+.3f} %)"
                + (f", tolerance {self.tolerance * 100:.1f} %"
                   if self.tolerance else "")
            )
        if self.evidence:
            lines.append(f"  {self.evidence}")
        if self.convergence:
            lines.append(f"  convergence: {self.convergence}")
        if self.run_directory:
            lines.append(f"  run archive: {self.run_directory}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.value,
            "status": self.status.value,
            "evidence": self.evidence,
            "measured": self.measured,
            "expected": self.expected,
            "tolerance": self.tolerance,
            "convergence": self.convergence,
            "run_directory": self.run_directory,
            "solver_version": self.solver_version,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityRecord":
        return cls(
            capability=Capability(data["capability"]),
            status=CapabilityStatus(data["status"]),
            evidence=data.get("evidence", ""),
            measured=data.get("measured"),
            expected=data.get("expected"),
            tolerance=data.get("tolerance"),
            convergence=data.get("convergence", ""),
            run_directory=data.get("run_directory"),
            solver_version=data.get("solver_version", ""),
            recorded_at=data.get("recorded_at", ""),
        )


#: The one capability whose answer is known without running anything.
#:
#: Phase 3 criterion 8 settled this against the manual: CalculiX has no
#: ``*VISCOELASTIC`` keyword (the index runs ``*VIEWFACTOR`` straight to ``*VISCO``),
#: ``*VISCO`` is a step card for viscoplastic analysis rather than a material,
#: ``*CREEP`` is irreversible overstress creep requiring ``*ELASTIC``, and no
#: ``*HYPERELASTIC`` model carries time or rate dependence. A ``umat`` is the only
#: route and is not documented as supported.
_VISCOELASTICITY_FINDING = CapabilityRecord(
    capability=Capability.VISCOELASTICITY,
    status=CapabilityStatus.NOT_AVAILABLE,
    evidence=(
        "CalculiX 2.23 has no viscoelastic material model. Checked against the "
        "manual in Phase 3 criterion 8 and recorded in "
        "docs/03-solver-comparison.md. No benchmark can change this; it needs a "
        "different solver or a user material subroutine."
    ),
)


def default_registry_path() -> Path:
    """Where the benchmark results live by default: ``results/phase6/``.

    Inside the repository rather than in a user directory, because the whole point is
    that a collaborator can read the evidence without re-running anything, and then
    re-run it if they do not believe it.
    """
    return (
        Path(__file__).resolve().parents[4]
        / "results" / "phase6" / "capabilities.json"
    )


@dataclass
class CapabilityRegistry:
    """What this installation has demonstrated, and what it has not."""

    records: dict[Capability, CapabilityRecord] = field(default_factory=dict)
    source: Path | None = None

    def __post_init__(self) -> None:
        # The viscoelasticity finding is not a benchmark result and is not waiting
        # for one, so it is present from the start unless a file overrides it.
        self.records.setdefault(Capability.VISCOELASTICITY, _VISCOELASTICITY_FINDING)

    # -- queries ---------------------------------------------------------------

    def record(self, capability: Capability) -> CapabilityRecord:
        return self.records.get(
            capability,
            CapabilityRecord(capability=capability,
                             status=CapabilityStatus.NOT_TESTED),
        )

    def status(self, capability: Capability) -> CapabilityStatus:
        return self.record(capability).status

    def is_enabled(self, capability: Capability) -> bool:
        """Whether the UI may offer this feature. Phase 6 criterion 2."""
        return self.status(capability).usable

    def require(self, capability: Capability) -> CapabilityRecord:
        """Return the record, or raise with the evidence against it.

        Called at the top of any analysis that depends on the capability. The error
        quotes the recorded evidence rather than saying "unsupported", because the
        reader's next question is always "says who".
        """
        record = self.record(capability)
        if record.status.usable:
            return record
        detail = record.evidence or (
            "No benchmark has been run for it on this installation. Run "
            "scripts/phase6_benchmarks.py."
        )
        raise CapabilityNotAvailableError(
            f"{capability.label} is not available: {record.status.label}. {detail}\n"
            f"What a passing benchmark requires: {capability.benchmark_description}"
        )

    def enabled(self) -> list[Capability]:
        return [c for c in Capability if self.is_enabled(c)]

    def summary(self) -> str:
        lines = ["Phase 6 capability status:"]
        for capability in Capability:
            lines.append("  " + self.record(capability).summary().replace("\n", "\n  "))
        return "\n".join(lines)

    # -- persistence -----------------------------------------------------------

    def set(self, record: CapabilityRecord) -> None:
        record.recorded_at = record.recorded_at or datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")
        self.records[record.capability] = record

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else (self.source or default_registry_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "format": 1,
                    "records": [r.as_dict() for r in self.records.values()],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.source = target
        return target

    @classmethod
    def load(cls, path: Path | str | None = None) -> "CapabilityRegistry":
        """Read a registry, or return an all-untested one if there is no file.

        A missing file is the normal state of a fresh checkout and is not an error.
        It leaves everything disabled, which is the safe direction.
        """
        target = Path(path) if path else default_registry_path()
        if not target.is_file():
            logger.info(
                "No capability registry at %s; every Phase 6 capability is untested "
                "and therefore disabled.", target,
            )
            return cls(source=target)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"The capability registry at {target} could not be read: {exc}. "
                "Delete it to start from untested, or fix it -- it is not guessed at, "
                "because a corrupt registry silently enabling a feature is the exact "
                "failure this file exists to prevent."
            ) from exc
        registry = cls(source=target)
        for entry in data.get("records", []):
            record = CapabilityRecord.from_dict(entry)
            registry.records[record.capability] = record
        return registry
