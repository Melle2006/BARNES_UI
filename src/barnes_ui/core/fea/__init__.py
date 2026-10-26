"""Finite element analysis: meshing, deck generation, solver execution, results.

Two backends, with sharply different roles:

**CalculiX** is the production solver. It is a native executable that must be installed
separately, and when it is absent FEA is *unavailable* -- never approximated. See
``solver.installation_instructions``.

**scikit-fem** is a verification backend only, in ``verification``. It solves linear
elasticity on the same mesh, which checks the mesh, the units, the boundary conditions
and the reaction extraction against beam theory. It says nothing about finite-strain or
hyperelastic behaviour, and nothing it produces is ever reported as a result.
"""

from .convergence import ConvergenceStudy, run_mesh_convergence
from .deck import BoundaryCondition, DeckError, DeckSettings, write_deck
from .meshing import Mesh, MeshingError, MeshSettings, generate_mesh
from .results import ConvergenceReport, FeaResult
from .runner import RunError, run_analysis
from .solver import (
    SolverInfo,
    SolverNotAvailableError,
    find_solver,
    installation_instructions,
    probe_solver,
    require_solver,
)

__all__ = [
    "BoundaryCondition",
    "ConvergenceReport",
    "ConvergenceStudy",
    "DeckError",
    "DeckSettings",
    "FeaResult",
    "Mesh",
    "MeshSettings",
    "MeshingError",
    "RunError",
    "SolverInfo",
    "SolverNotAvailableError",
    "find_solver",
    "generate_mesh",
    "installation_instructions",
    "probe_solver",
    "require_solver",
    "run_analysis",
    "run_mesh_convergence",
    "write_deck",
]
