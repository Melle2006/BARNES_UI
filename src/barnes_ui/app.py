"""Application bootstrap.

Sets up logging, installs an exception hook, creates the Qt application and shows the
main window.
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from types import TracebackType

from . import __version__
from .core.logging_setup import configure_logging, log_file_path

logger = logging.getLogger(__name__)

__all__ = ["run"]


def _install_exception_hook() -> None:
    """Show unhandled exceptions instead of letting the window vanish.

    Without this, an exception raised inside a Qt slot prints to a console nobody is
    watching and the application either dies silently or carries on in an undefined
    state. Neither is acceptable in a tool whose output people make engineering
    decisions from.
    """
    original_hook = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            original_hook(exc_type, exc_value, exc_tb)
            return

        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("Unhandled exception:\n%s", detail)

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("Unexpected error")
                box.setText(
                    f"{exc_type.__name__}: {exc_value}\n\n"
                    "The application may be in an inconsistent state. Saving your "
                    "work and restarting is advisable.\n\n"
                    f"Full details were written to:\n{log_file_path()}"
                )
                box.setDetailedText(detail)
                box.exec()
        except Exception:  # pragma: no cover - the dialog itself failed
            original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    """Start the application. Returns the process exit code.

    An optional file path on the command line is opened at startup, which makes
    testing against a particular part a one-liner rather than four clicks.
    """
    argv = list(sys.argv if argv is None else argv)

    configure_logging()
    logger.info("Barnes UI %s starting", __version__)

    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Barnes UI")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Barnes")

    _install_exception_hook()

    window = MainWindow()
    window.show()

    # A path given on the command line is loaded once the event loop is running, so
    # that the window is already visible if the import is slow or fails.
    candidates = [a for a in argv[1:] if not a.startswith("-")]
    if candidates:
        path = Path(candidates[0])
        if path.is_file():
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: window.load_file(path))
        else:
            logger.warning("Ignoring command-line path that is not a file: %s", path)

    return app.exec()
