"""Barnes UI -- TPU flexure design, stiffness analysis and prosthetic-hand simulation.

Package layout is described in ``docs/04-architecture.md``. The one rule to know
before editing anything: ``barnes_ui.core`` must never import GUI libraries. It is
enforced by ``tests/test_architecture.py``.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
