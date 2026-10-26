"""Application logging.

Logs go to a rotating file as well as the console. The file matters because the most
useful bug reports are the ones where the user can attach a log, and because solver
output in later phases is far too verbose for a console.

The log path is shown in Help > About so it can be found without hunting.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

__all__ = ["configure_logging", "log_directory", "log_file_path"]

_CONSOLE_FORMAT = "%(levelname)-8s %(name)s: %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d  %(message)s"

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

_configured = False


def log_directory() -> Path:
    """Where logs are written.

    Deliberately outside the project tree. This project lives under a OneDrive-synced
    folder, and having OneDrive attempt to sync a log file that is being appended to
    several times a second is a recipe for lock contention and spurious conflict
    copies. The same reasoning applies to solver scratch directories in Phase 3.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "BarnesUI" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "BarnesUI"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "barnes-ui"


def log_file_path() -> Path:
    return log_directory() / "barnes-ui.log"


def configure_logging(level: int = logging.INFO, console: bool = True) -> Path | None:
    """Set up logging for the application.

    Idempotent: calling it twice does not duplicate handlers, which otherwise produces
    every message twice and is a classic way to make a log unreadable.

    Returns the log file path, or ``None`` when the file handler could not be created.
    A failure to open a log file never prevents the application from starting -- it
    degrades to console only.
    """
    global _configured
    if _configured:
        return log_file_path()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # handlers filter; the root must let everything past

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        root.addHandler(handler)

    path: Path | None = None
    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "barnes-ui.log"
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not open a log file (%s). Continuing with console logging only.",
            exc,
        )
        path = None

    # VTK and Matplotlib are chatty at DEBUG and drown out everything useful.
    for noisy in ("matplotlib", "PIL", "trimesh", "vtkmodules"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).debug("Logging configured; file=%s", path)
    return path
