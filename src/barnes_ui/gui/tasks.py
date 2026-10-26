"""Background execution for long-running work.

Importing a large assembly takes seconds; meshing and solving in later phases take
minutes. None of it may block the UI thread.

The contract this module provides, which every long operation uses:

* work runs on a ``QThread``
* progress is reported as (fraction, message)
* cancellation is cooperative -- the worker checks a token and stops at a safe point
* exceptions are marshalled back to the UI thread and surfaced, never swallowed
* exactly one of ``finished`` or ``failed`` is emitted, so callers can always
  re-enable their UI

The core library knows nothing about any of this. A core function takes an optional
``progress`` callable and an optional :class:`CancellationToken`, both plain Python
objects, which keeps it usable from a script.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)

__all__ = ["CancellationToken", "Cancelled", "Worker", "run_in_background"]


class Cancelled(Exception):
    """Raised inside a worker when cancellation has been requested."""


class CancellationToken:
    """A cooperative cancellation flag.

    Cooperative rather than forced because killing a thread midway through an
    OpenCASCADE call would leave the kernel's internal state undefined. The worker
    checks the token at points where stopping is safe.
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise Cancelled("Operation cancelled by the user.")


class Worker(QObject):
    """Runs a callable on a worker thread and reports the outcome.

    Signals
    -------
    progress(float, str)
        Fraction complete in [0, 1] and a human-readable status. A negative fraction
        means indeterminate, for operations that cannot estimate their own progress.
    finished(object)
        The callable's return value.
    failed(str, str)
        A user-facing message and the full traceback. Both are provided because the
        message goes in a dialog and the traceback goes in the log.
    cancelled()
        The operation stopped because cancellation was requested.
    """

    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        function: Callable[..., Any],
        *args: Any,
        accepts_progress: bool = False,
        accepts_token: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._accepts_progress = accepts_progress
        self._accepts_token = accepts_token
        self.token = CancellationToken()

    def run(self) -> None:
        """Execute the callable. Connected to the thread's ``started`` signal."""
        try:
            kwargs = dict(self._kwargs)
            if self._accepts_progress:
                kwargs["progress"] = self._emit_progress
            if self._accepts_token:
                kwargs["cancellation"] = self.token

            result = self._function(*self._args, **kwargs)

            if self.token.is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(result)

        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            # Every exception is caught on purpose. An exception escaping a worker
            # thread's slot terminates the thread silently, and the user is left
            # looking at a UI that never stops saying "working".
            detail = traceback.format_exc()
            logger.error("Background task failed: %s\n%s", exc, detail)
            self.failed.emit(str(exc), detail)

    def _emit_progress(self, fraction: float, message: str = "") -> None:
        self.progress.emit(float(fraction), message)


def run_in_background(
    parent: QObject,
    function: Callable[..., Any],
    *args: Any,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str, str], None] | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    on_cancelled: Callable[[], None] | None = None,
    accepts_progress: bool = False,
    accepts_token: bool = False,
    **kwargs: Any,
) -> tuple[QThread, Worker]:
    """Start ``function`` on a worker thread and wire up the callbacks.

    Returns ``(thread, worker)``. The caller must keep a reference to both: if either
    is garbage collected while the thread is running, Qt tears down the underlying
    object and the application crashes. This is the single most common mistake with
    QThread, which is why it is said here rather than left to be discovered.

    Call ``worker.token.cancel()`` to request cancellation.
    """
    thread = QThread(parent)
    worker = Worker(
        function, *args,
        accepts_progress=accepts_progress,
        accepts_token=accepts_token,
        **kwargs,
    )
    worker.moveToThread(thread)

    thread.started.connect(worker.run)

    if on_progress is not None:
        worker.progress.connect(on_progress)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_failed is not None:
        worker.failed.connect(on_failed)
    if on_cancelled is not None:
        worker.cancelled.connect(on_cancelled)

    # Whichever terminal signal fires, quit the event loop and schedule cleanup.
    for signal in (worker.finished, worker.failed, worker.cancelled):
        signal.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
