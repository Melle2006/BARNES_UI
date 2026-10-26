"""Engineering core: CAD, mechanics, solvers and project storage.

Nothing in this subpackage may import PySide6, PyVista or Matplotlib. The separation
keeps the physics testable without a display and usable from a plain script, and it is
checked by an automated test rather than left to discipline.
"""
