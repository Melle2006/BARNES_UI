"""Locating CalculiX and reporting what it can do.

CalculiX is a native executable, not a Python package, so it has to be found rather
than imported. This module is the single place that happens, and the single place that
decides whether FEA is available at all.

The rule this module exists to enforce
--------------------------------------

**When the solver is absent, FEA is unavailable. It is never approximated.**

``docs/05-development-plan.md`` makes this Phase 3 acceptance criterion 6: with
CalculiX missing, FEA features are disabled with an installation message and the
application does not fall back to the reduced-order model. A reduced-order result
presented where an FEA result was asked for is precisely the "plausible but physically
wrong" failure the whole project is built to avoid, and it would be worse here than
anywhere, because the user explicitly asked for the high-fidelity answer.

So :func:`find_solver` returns ``None`` rather than a substitute, and every caller is
expected to surface that rather than work around it.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "SolverInfo",
    "find_solver",
    "probe_solver",
    "installation_instructions",
    "SolverNotAvailableError",
]


class SolverNotAvailableError(RuntimeError):
    """CalculiX could not be found or could not be run."""


#: Environment variable checked before anything else, so a user can point the
#: application at a specific build without touching PATH.
_ENV_VAR = "BARNES_UI_CCX"

#: Executable names CalculiX is distributed under.
_EXECUTABLE_NAMES = ("ccx", "ccx.exe", "ccx_static.exe", "CalculiX.exe")

#: Places a Windows CalculiX commonly lands, searched after PATH. FreeCAD bundles
#: ccx and is the easiest legitimate way to obtain it without a separate download.
_WINDOWS_HINTS = (
    r"C:\Program Files\FreeCAD*\bin",
    r"C:\Program Files\FreeCAD*\lib",
    r"C:\Program Files\bConverged\CalculiX\ccx",
    r"C:\CalculiX\ccx*\src",
    r"C:\Program Files\CalculiX*",
)


@dataclass
class SolverInfo:
    """A located CalculiX executable and what was learned about it."""

    executable: Path
    version: str = "unknown"
    #: Raw first lines of the solver's own banner, kept verbatim for the run manifest.
    banner: str = ""
    #: Capabilities confirmed by actually exercising them, not by assumption.
    verified_capabilities: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.executable.is_file()

    def describe(self) -> str:
        return f"CalculiX {self.version} at {self.executable}"


def find_solver(explicit: Path | str | None = None) -> SolverInfo | None:
    """Locate the CalculiX executable, or return ``None``.

    Search order: an explicitly supplied path, then ``BARNES_UI_CCX``, then ``PATH``,
    then a short list of conventional Windows install locations.

    Returns ``None`` rather than raising, because "no solver" is a normal state the UI
    has to present, not an exceptional one. Callers that genuinely require a solver
    raise :class:`SolverNotAvailableError` with
    :func:`installation_instructions` in the message.
    """
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    from_env = os.environ.get(_ENV_VAR)
    if from_env:
        candidates.append(Path(from_env))

    for name in _EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for pattern in _WINDOWS_HINTS:
        parent = Path(pattern).parent
        try:
            for directory in parent.parent.glob(parent.name):
                for name in _EXECUTABLE_NAMES:
                    candidates.append(directory / name)
        except (OSError, ValueError):  # pragma: no cover - malformed pattern or drive
            continue

    for candidate in candidates:
        if candidate.is_file():
            logger.info("Found CalculiX at %s", candidate)
            return SolverInfo(executable=candidate)

    logger.info(
        "CalculiX was not found. Searched %s, PATH, and %d conventional locations.",
        _ENV_VAR, len(_WINDOWS_HINTS),
    )
    return None


def probe_solver(info: SolverInfo, timeout: float = 30.0) -> SolverInfo:
    """Run the solver once to confirm it starts and to read its version.

    Starting is not the same as being installed. A build missing a runtime DLL sits on
    disk looking perfectly fine and fails the moment it is invoked, so this executes it
    before anything depends on it.

    CalculiX with no input file prints its banner and exits non-zero, which is the
    expected outcome here -- a non-zero exit is not treated as failure, only an
    inability to start.
    """
    try:
        completed = subprocess.run(
            [str(info.executable)],
            capture_output=True, text=True, timeout=timeout,
            # Run somewhere harmless: ccx writes scratch files into its working
            # directory, and that must not be the user's project.
            cwd=str(info.executable.parent),
        )
    except FileNotFoundError as exc:
        raise SolverNotAvailableError(
            f"{info.executable} exists but could not be executed: {exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SolverNotAvailableError(
            f"{info.executable} did not respond within {timeout} s. It may be waiting "
            "for input, which means the build is not the command-line ccx."
        ) from exc
    except OSError as exc:
        raise SolverNotAvailableError(
            f"{info.executable} could not be started: {exc}\n\n"
            "On Windows this usually means a missing runtime DLL beside the "
            "executable."
        ) from exc

    banner = (completed.stdout or "") + (completed.stderr or "")
    info.banner = "\n".join(banner.splitlines()[:6])

    match = re.search(r"[Vv]ersion\s+([0-9][0-9.]*)", banner)
    if match:
        info.version = match.group(1)
    else:
        info.notes.append(
            "The solver started but its banner did not contain a recognisable version "
            "string. The banner is archived with each run regardless."
        )

    logger.info("CalculiX probe: version=%s", info.version)
    return info


def installation_instructions() -> str:
    """What to tell the user when CalculiX is missing.

    Concrete, because "install CalculiX" is not actionable to someone who has not done
    it before, and because the FreeCAD route is much less well known than it should be.
    """
    return (
        "CalculiX (ccx) is required for finite element analysis and was not found.\n\n"
        "It is a native executable rather than a Python package, so it has to be "
        "installed separately. Two routes on Windows:\n\n"
        "  1. FreeCAD (easiest). FreeCAD bundles ccx.exe. Install FreeCAD, then point "
        "     this application at the bundled solver -- it is usually at\n"
        "     C:\\Program Files\\FreeCAD <version>\\bin\\ccx.exe\n\n"
        "  2. bConverged 'CalculiX for Windows', which packages ccx with its "
        "     supporting tools.\n\n"
        "Then either put the executable on PATH, or set the environment variable\n"
        f"  {_ENV_VAR}=C:\\path\\to\\ccx.exe\n\n"
        "Until then, FEA is unavailable. The application will not substitute a "
        "reduced-order result for one you asked a solver for."
    )


def require_solver(explicit: Path | str | None = None) -> SolverInfo:
    """Locate and probe the solver, raising with instructions if unavailable."""
    info = find_solver(explicit)
    if info is None:
        raise SolverNotAvailableError(installation_instructions())
    return probe_solver(info)
