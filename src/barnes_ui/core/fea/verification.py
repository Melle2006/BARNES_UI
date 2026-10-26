"""An independent, pip-installable FE backend, used for verification.

Why a second solver
-------------------

``docs/03-solver-comparison.md`` selected CalculiX as the production solver and planned
FEniCSx as an independent second opinion, on the grounds that unit errors and
boundary-condition mistakes are likelier sources of a wrong answer than the solver
itself. FEniCSx turned out to need conda or WSL on Windows, which defeats the purpose
of a check that must be easy to run.

``scikit-fem`` fills the role instead: pure Python, installs with pip, works on Windows,
and is a genuinely different implementation rather than a wrapper around the same
kernel. It is used here **only for verification**, never for production results.

What it covers, and what it does not
------------------------------------

This backend solves **linear elasticity** on the same mesh the CalculiX pipeline
generates. That verifies a specific and valuable set of things:

* the Gmsh mesh is well formed and usable by a real solver;
* node ordering, units and the element definition are right;
* boundary-condition application and reaction extraction are right;
* tip deflection matches beam theory, which is Phase 3 acceptance criterion 1.

It does **not** cover finite-strain kinematics or hyperelastic material response. Those
need the production solver. A linear check that passes says the plumbing is sound; it
says nothing about whether the nonlinear physics is right, and this module does not
pretend otherwise.

Deliberately not used to produce any result the application reports. Its outputs are
tagged ``ANALYTICAL_ESTIMATE`` at best and exist to be compared against, not quoted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .meshing import Mesh

logger = logging.getLogger(__name__)

__all__ = [
    "LinearSolution",
    "solve_linear_elastic",
    "cantilever_tip_deflection",
    "VerificationError",
]


class VerificationError(RuntimeError):
    """The verification solve could not be carried out."""


@dataclass
class LinearSolution:
    """Result of a linear-elastic verification solve."""

    #: Total reaction force on the constrained boundary, N.
    reaction_force: np.ndarray
    #: Degrees of freedom actually solved for.
    dof_count: int
    #: Callable giving displacement (3,) in mm at any point, for probing.
    probe: object = None
    notes: list[str] = field(default_factory=list)

    def displacement_at(self, point: Sequence[float]) -> np.ndarray:
        """Displacement vector at a point in the model, mm."""
        if self.probe is None:  # pragma: no cover - set by the solver
            raise VerificationError("This solution carries no interpolator.")
        coords = np.asarray(point, dtype=float).reshape(3, 1)
        return np.asarray(self.probe(coords), dtype=float).ravel()


def solve_linear_elastic(
    mesh: Mesh,
    youngs_modulus: float,
    poisson_ratio: float,
    fixed_where,
    loaded_where,
    total_force: Sequence[float],
) -> LinearSolution:
    """Solve a linear-elastic problem on ``mesh``.

    ``fixed_where`` and ``loaded_where`` are predicates on a ``(3, n)`` array of
    coordinates, selecting boundary facets. Predicates rather than node index lists,
    because scikit-fem's second-order basis carries mid-edge degrees of freedom whose
    ordering is internal to the library -- an earlier version of this function assumed
    the first ``3 * n_points`` DOFs were the corner nodes in mesh order and produced a
    singular matrix, which is what that assumption deserves.

    The load is applied as a uniform traction over the selected facets, integrated
    consistently, rather than lumped onto nodes. That is both more correct and simpler
    than distributing a resultant by hand.

    Second-order (P2) elements are used, matching the production pipeline's ``C3D10``.
    Using P1 here would make the comparison test element order rather than the pipeline.
    """
    try:
        from skfem import (
            Basis, ElementTetP2, ElementVector, FacetBasis, Functional, LinearForm,
            MeshTet, asm, condense, solve,
        )
        from skfem.models.elasticity import linear_elasticity
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise VerificationError(
            "scikit-fem is required for the verification backend. Install it with: "
            "pip install scikit-fem"
        ) from exc

    if poisson_ratio >= 0.5:
        raise VerificationError(
            f"Poisson's ratio of {poisson_ratio} is incompressible, which linear "
            "displacement elements cannot represent. Use a near-incompressible value."
        )

    # scikit-fem wants (3, n_points) and (4, n_elements); the project stores the
    # transpose. It also wants a clean P1 topology, and builds its own P2 mid-edge
    # degrees of freedom from it.
    #
    # The mesh here is second order, so its node array holds both corner and mid-edge
    # nodes while only the corners appear in the connectivity. Handing the whole array
    # over leaves thousands of vertices unreferenced -- 2048 of 4658 on the test
    # cantilever -- and scikit-fem silently renumbered them away, producing a basis
    # with 5490 unconnected degrees of freedom and an exactly singular stiffness
    # matrix. The symptom pointed at the boundary conditions; the cause was here.
    #
    # So the corner nodes are extracted and compacted, and the connectivity remapped
    # onto the new numbering, before anything is handed over.
    corner_ids = np.unique(mesh.elements[:, :4])
    remap = np.full(mesh.nodes.shape[0], -1, dtype=np.int64)
    remap[corner_ids] = np.arange(corner_ids.size, dtype=np.int64)

    points = np.ascontiguousarray(mesh.nodes[corner_ids].T, dtype=np.float64)
    corners = np.ascontiguousarray(remap[mesh.elements[:, :4]].T, dtype=np.int64)
    if np.any(corners < 0):  # pragma: no cover - would mean a corrupt connectivity
        raise VerificationError(
            "The mesh connectivity references nodes that are not in its node array."
        )

    try:
        skmesh = MeshTet(points, corners)
    except Exception as exc:
        raise VerificationError(
            f"scikit-fem rejected the mesh: {exc}. This usually means inverted or "
            "degenerate elements -- check the mesh quality metrics."
        ) from exc

    element = ElementVector(ElementTetP2())
    basis = Basis(skmesh, element)

    lame_lambda = (
        youngs_modulus * poisson_ratio
        / ((1.0 + poisson_ratio) * (1.0 - 2.0 * poisson_ratio))
    )
    lame_mu = youngs_modulus / (2.0 * (1.0 + poisson_ratio))
    stiffness = asm(linear_elasticity(lame_lambda, lame_mu), basis)

    constrained = basis.get_dofs(skmesh.facets_satisfying(fixed_where))
    if np.asarray(constrained.all()).size == 0:
        raise VerificationError(
            "The fixed predicate selected no boundary facets, so the model has "
            "rigid-body modes and the stiffness matrix is singular."
        )

    loaded_facets = skmesh.facets_satisfying(loaded_where)
    if loaded_facets.size == 0:
        raise VerificationError("The load predicate selected no boundary facets.")

    facet_basis = FacetBasis(skmesh, element, facets=loaded_facets)

    # Convert the resultant into a uniform traction over the selected area, so the
    # integrated load equals the requested force whatever the mesh density.
    @Functional
    def area_form(w):
        return 1.0 + 0.0 * w.x[0]

    area = float(asm(area_form, facet_basis))
    if area <= 0:  # pragma: no cover - degenerate selection
        raise VerificationError("The loaded facets have zero area.")
    traction = np.asarray(total_force, dtype=float) / area

    @LinearForm
    def loading(v, w):
        return traction[0] * v[0] + traction[1] * v[1] + traction[2] * v[2]

    load = asm(loading, facet_basis)

    displacement = solve(*condense(stiffness, load, D=constrained))

    # Reaction on the constrained boundary is the residual there, summed per component.
    residual = stiffness @ displacement - load
    fixed_dofs = np.asarray(constrained.all(), dtype=np.int64)
    reaction = np.array([
        float(residual[fixed_dofs[fixed_dofs % 3 == component]].sum())
        for component in range(3)
    ])

    solution = LinearSolution(
        reaction_force=reaction,
        dof_count=int(stiffness.shape[0]),
        probe=basis.interpolator(displacement),
    )
    solution.notes.append(
        f"scikit-fem P2 tetrahedra, {stiffness.shape[0]} degrees of freedom, "
        f"lambda={lame_lambda:.6g} MPa, mu={lame_mu:.6g} MPa, "
        f"loaded area {area:.6g} mm^2."
    )
    solution.notes.append(
        "Linear elasticity only. This verifies the mesh, units, boundary conditions "
        "and reaction extraction; it says nothing about finite-strain or hyperelastic "
        "behaviour."
    )
    logger.info("Verification solve: %s", solution.notes[0])
    return solution


def cantilever_tip_deflection(
    force: float,
    length: float,
    width: float,
    height: float,
    youngs_modulus: float,
    poisson_ratio: float = 0.3,
    include_shear: bool = True,
) -> float:
    """Analytical tip deflection of an end-loaded cantilever, mm.

    Euler-Bernoulli with an optional Timoshenko shear term:

        delta = F L^3 / (3 E I)  +  F L / (k G A)

    with ``I = w h^3 / 12`` for bending about the width axis and ``k = 5/6`` for a
    rectangular section.

    The shear term is included by default because it is not always negligible. For the
    20 x 4 x 2 mm bar used in the tests, at a span-to-depth ratio of 10, it contributes
    about 0.8 per cent; at a ratio of 5 it is over 3 per cent, which would swamp the
    tolerance the comparison is run at.

    A caution on what this can validate: a 3D finite element cantilever is genuinely
    *stiffer* than beam theory predicts, because a fully clamped end face restrains the
    Poisson contraction that beam theory allows freely. A few per cent of disagreement
    is physics, not error, and the acceptance tolerance has to allow for it.
    """
    second_moment = width * height**3 / 12.0
    bending = force * length**3 / (3.0 * youngs_modulus * second_moment)
    if not include_shear:
        return bending
    shear_modulus = youngs_modulus / (2.0 * (1.0 + poisson_ratio))
    area = width * height
    shear = force * length / ((5.0 / 6.0) * shear_modulus * area)
    return bending + shear
