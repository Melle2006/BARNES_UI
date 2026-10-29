"""Material models for TPU.

What this module refuses to do
------------------------------

It will not invent hyperelastic coefficients from a hardness grade. "TPU 90A" names a
Shore A hardness; it does not determine a stress-strain curve. Filaments sold under the
same grade differ materially, and a printed part differs again from bulk material
through layer adhesion, print orientation and infill, and is anisotropic along the
build direction.

The filament in use is SUNLU TPU 90A, 1.75 mm. Its published data does not change any of
the above: the sheet carries no modulus and no stress-strain curve, and its mechanical
rows are not self-consistent -- an elongation at break of 10 +/- 5 % for a material the
same manufacturer's store lists at >=1000 %, a Shore figure of 80 on a product sold as
90A, and a flexural strength a 90A elastomer does not meaningfully have. The one figure
taken from it is density, 1.23 g/cm^3, which is a physical property rather than a
constitutive one. See docs/06-required-inputs.md item 7.

Correlations from Shore hardness to an elastic modulus exist. They carry large scatter
and they give a *small-strain* modulus, which is not the quantity a Mooney-Rivlin or
Ogden fit needs. Using one to populate hyperelastic constants would produce numbers
that look authoritative and are not, so :func:`provisional_tpu` exists instead: it
returns a clearly flagged placeholder whose every derived result carries the
assumed-material caveat for the rest of its life.

Calibration
-----------

:meth:`HyperelasticModel.fit_uniaxial` fits a model to measured engineering
stress-strain data and records the strain range it was fitted over.
:meth:`is_within_calibration` then reports whether a simulation is extrapolating.

A fit is only valid over the range it was fitted on. More parameters is not more
accurate: a three-term Ogden has enough freedom to fit almost any single curve
beautifully and then extrapolate badly, so with only one uniaxial curve available a
Neo-Hookean or two-term Mooney-Rivlin fit is the defensible choice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np

from ..provenance import CAVEAT_ASSUMED_MATERIAL, Caveat, Provenance, TaggedValue

logger = logging.getLogger(__name__)

__all__ = [
    "MaterialModelKind",
    "HyperelasticModel",
    "provisional_tpu",
    "CAVEAT_OUTSIDE_CALIBRATION",
    "CAVEAT_DATASHEET_DERIVED",
]


CAVEAT_OUTSIDE_CALIBRATION = Caveat(
    "outside_calibration",
    "The analysis drives the material outside the strain range its parameters were "
    "fitted over. Hyperelastic fits extrapolate poorly; treat the result as "
    "indicative only.",
)
CAVEAT_DATASHEET_DERIVED = Caveat(
    "datasheet_derived",
    "Material parameters come from a manufacturer datasheet, which describes bulk "
    "material rather than a 3D-printed part. Printed TPU differs through layer "
    "adhesion, orientation and infill, and is anisotropic along the build direction.",
)


class MaterialModelKind(Enum):
    """Supported strain-energy functions.

    ``parameter_names`` are the coefficients in the order ``parameters`` stores them.
    All coefficients are in MPa except the Ogden exponents, which are dimensionless.
    """

    LINEAR_ELASTIC = ("Linear elastic", ("E", "nu"))
    NEO_HOOKEAN = ("Neo-Hookean", ("C10",))
    MOONEY_RIVLIN = ("Mooney-Rivlin", ("C10", "C01"))
    OGDEN_1 = ("Ogden (N=1)", ("mu1", "alpha1"))
    OGDEN_2 = ("Ogden (N=2)", ("mu1", "alpha1", "mu2", "alpha2"))

    def __init__(self, label: str, parameter_names: tuple[str, ...]) -> None:
        self.label = label
        self.parameter_names = parameter_names

    @property
    def is_hyperelastic(self) -> bool:
        return self is not MaterialModelKind.LINEAR_ELASTIC

    @property
    def calculix_keyword(self) -> str | None:
        """The CalculiX ``*HYPERELASTIC`` model name, for Phase 3 deck generation.

        Returned for reference only. Phase 3 must still confirm the coefficient
        ordering CalculiX expects, and note that its Ogden formulation follows the
        Abaqus convention rather than Ogden's original -- coefficients taken from a
        paper using the original form cannot be pasted in unchanged.
        """
        return {
            MaterialModelKind.NEO_HOOKEAN: "NEO HOOKE",
            MaterialModelKind.MOONEY_RIVLIN: "MOONEY-RIVLIN",
            MaterialModelKind.OGDEN_1: "OGDEN",
            MaterialModelKind.OGDEN_2: "OGDEN",
        }.get(self)


@dataclass
class HyperelasticModel:
    """A material definition with its parameters, provenance and validity range.

    ``provenance`` records where the parameters came from, and it is carried into every
    result computed with this material. A model built by :func:`provisional_tpu` is
    tagged ``UNVALIDATED_ASSUMPTION`` and cannot be promoted by anything short of
    fitting it to real data.
    """

    kind: MaterialModelKind
    parameters: tuple[float, ...]
    name: str = "TPU"
    poisson_ratio: float = 0.4995
    provenance: Provenance = Provenance.UNVALIDATED_ASSUMPTION
    caveats: tuple[Caveat, ...] = (CAVEAT_ASSUMED_MATERIAL,)
    #: Engineering-strain range the parameters were fitted over, if they were fitted.
    calibration_strain_range: tuple[float, float] | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        expected = len(self.kind.parameter_names)
        if len(self.parameters) != expected:
            raise ValueError(
                f"{self.kind.label} needs {expected} parameter(s) "
                f"{self.kind.parameter_names}, got {len(self.parameters)}."
            )
        if self.kind is MaterialModelKind.LINEAR_ELASTIC:
            # For a linear material nu is one of the parameters, so keep the dedicated
            # field consistent with it rather than letting the two disagree.
            self.poisson_ratio = self.parameters[1]

    # -- elastic constants ----------------------------------------------------

    @property
    def initial_shear_modulus(self) -> float:
        """Small-strain shear modulus mu0, MPa.

        Neo-Hookean:    mu0 = 2*C10
        Mooney-Rivlin:  mu0 = 2*(C10 + C01)
        Ogden:          mu0 = 0.5 * sum(mu_i * alpha_i)
        Linear elastic: mu0 = E / (2*(1+nu))
        """
        if self.kind is MaterialModelKind.LINEAR_ELASTIC:
            E, nu = self.parameters
            return E / (2.0 * (1.0 + nu))
        if self.kind is MaterialModelKind.NEO_HOOKEAN:
            return 2.0 * self.parameters[0]
        if self.kind is MaterialModelKind.MOONEY_RIVLIN:
            return 2.0 * (self.parameters[0] + self.parameters[1])
        if self.kind in (MaterialModelKind.OGDEN_1, MaterialModelKind.OGDEN_2):
            pairs = np.asarray(self.parameters, dtype=float).reshape(-1, 2)
            return 0.5 * float(np.sum(pairs[:, 0] * pairs[:, 1]))
        raise NotImplementedError(self.kind)  # pragma: no cover

    @property
    def initial_youngs_modulus(self) -> float:
        """Small-strain Young's modulus E, MPa.

        E = 2*mu0*(1+nu). For the near-incompressible default nu = 0.4995 this is
        essentially 3*mu0.

        This is the *initial tangent* modulus. It describes the material only near zero
        strain. A linear beam model built on it is a small-strain screening tool and
        says nothing reliable about a flexure at finger-joint deflections, which is why
        every result derived from it is tagged as a reduced-order prediction.
        """
        if self.kind is MaterialModelKind.LINEAR_ELASTIC:
            return self.parameters[0]
        return 2.0 * self.initial_shear_modulus * (1.0 + self.poisson_ratio)

    # -- uniaxial response ----------------------------------------------------

    def uniaxial_engineering_stress(self, stretch: np.ndarray | float) -> np.ndarray:
        """Engineering (nominal) stress for incompressible uniaxial extension, MPa.

        Takes stretch lambda = 1 + engineering strain. Assumes incompressibility, so
        the transverse stretches are lambda^(-1/2).

        Neo-Hookean:   P = 2*C10*(lam - lam^-2)
        Mooney-Rivlin: P = 2*(lam - lam^-2)*(C10 + C01/lam)
        Ogden:         P = sum( mu_i * (lam^(alpha_i - 1) - lam^(-alpha_i/2 - 1)) )
        """
        lam = np.asarray(stretch, dtype=float)
        if np.any(lam <= 0):
            raise ValueError("Stretch must be positive.")

        if self.kind is MaterialModelKind.LINEAR_ELASTIC:
            # Only meaningful near lam = 1; included so the model types are uniform.
            return self.parameters[0] * (lam - 1.0)

        if self.kind is MaterialModelKind.NEO_HOOKEAN:
            c10 = self.parameters[0]
            return 2.0 * c10 * (lam - lam**-2.0)

        if self.kind is MaterialModelKind.MOONEY_RIVLIN:
            c10, c01 = self.parameters
            return 2.0 * (lam - lam**-2.0) * (c10 + c01 / lam)

        if self.kind in (MaterialModelKind.OGDEN_1, MaterialModelKind.OGDEN_2):
            pairs = np.asarray(self.parameters, dtype=float).reshape(-1, 2)
            total = np.zeros_like(lam)
            for mu, alpha in pairs:
                total = total + mu * (lam ** (alpha - 1.0) - lam ** (-alpha / 2.0 - 1.0))
            return total

        raise NotImplementedError(self.kind)  # pragma: no cover

    def uniaxial_true_stress(self, stretch: np.ndarray | float) -> np.ndarray:
        """Cauchy (true) stress, MPa. Equals engineering stress times stretch."""
        lam = np.asarray(stretch, dtype=float)
        return self.uniaxial_engineering_stress(lam) * lam

    # -- calibration ----------------------------------------------------------

    def is_within_calibration(self, engineering_strain: float) -> bool:
        """Whether a strain lies inside the fitted range.

        Returns False when the model was never calibrated, because an uncalibrated
        model is outside its validity range everywhere.
        """
        if self.calibration_strain_range is None:
            return False
        low, high = self.calibration_strain_range
        return low <= engineering_strain <= high

    def caveats_for_strain(self, engineering_strain: float) -> tuple[Caveat, ...]:
        """The caveats that apply when the material is driven to a given strain."""
        caveats = tuple(self.caveats)
        if self.calibration_strain_range is not None and not self.is_within_calibration(
            engineering_strain
        ):
            caveats = caveats + (CAVEAT_OUTSIDE_CALIBRATION,)
        return caveats

    def tagged_youngs_modulus(self) -> TaggedValue:
        return TaggedValue(
            self.initial_youngs_modulus, "MPa", self.provenance,
            caveats=tuple(self.caveats), label=f"{self.name} initial Young's modulus",
        )

    @classmethod
    def fit_uniaxial(
        cls,
        strain: Sequence[float],
        stress: Sequence[float],
        kind: MaterialModelKind = MaterialModelKind.MOONEY_RIVLIN,
        name: str = "TPU (fitted)",
        poisson_ratio: float = 0.4995,
        from_datasheet: bool = False,
    ) -> "HyperelasticModel":
        """Fit a model to measured uniaxial engineering stress-strain data.

        ``strain`` is engineering strain (dimensionless), ``stress`` engineering stress
        in MPa. Both must be the same length, with at least as many points as the model
        has parameters.

        The fit is a bounded least-squares minimisation. The fitted strain range is
        recorded so that :meth:`is_within_calibration` can flag extrapolation later.

        Provenance is set to ANALYTICAL_ESTIMATE rather than anything stronger: fitted
        parameters reproduce the test they were fitted to, which is not the same as
        having been validated against an independent measurement. Only a comparison
        against a separate physical test earns EXPERIMENTALLY_VALIDATED, and that is
        applied by a human through the validation workflow, never here.
        """
        from scipy.optimize import least_squares

        e = np.asarray(strain, dtype=float)
        s = np.asarray(stress, dtype=float)
        if e.shape != s.shape:
            raise ValueError("strain and stress must have the same length.")
        if e.size < len(kind.parameter_names):
            raise ValueError(
                f"{kind.label} has {len(kind.parameter_names)} parameters but only "
                f"{e.size} data point(s) were supplied."
            )
        if np.any(e <= -1.0):
            raise ValueError("Engineering strain must be greater than -1.")

        lam = 1.0 + e

        def residual(p: np.ndarray) -> np.ndarray:
            trial = cls(kind=kind, parameters=tuple(p), poisson_ratio=poisson_ratio)
            return trial.uniaxial_engineering_stress(lam) - s

        guess, bounds = _initial_guess(kind, e, s)
        result = least_squares(residual, guess, bounds=bounds, max_nfev=20000)

        model = cls(
            kind=kind,
            parameters=tuple(float(v) for v in result.x),
            name=name,
            poisson_ratio=poisson_ratio,
            provenance=Provenance.ANALYTICAL_ESTIMATE,
            caveats=(CAVEAT_DATASHEET_DERIVED,) if from_datasheet else (),
            calibration_strain_range=(float(e.min()), float(e.max())),
        )

        predicted = model.uniaxial_engineering_stress(lam)
        rms = float(np.sqrt(np.mean((predicted - s) ** 2)))
        spread = float(np.ptp(s))
        model.notes.append(
            f"Fitted to {e.size} points over engineering strain "
            f"{e.min():.4f} to {e.max():.4f}. RMS residual {rms:.5f} MPa"
            + (f" ({100.0 * rms / spread:.2f}% of the stress range)." if spread > 0 else ".")
        )
        model.notes.append(
            "Valid only over the fitted strain range. Extrapolation beyond it is "
            "flagged on any result that relies on it."
        )
        return model

    def describe(self) -> str:
        parts = ", ".join(
            f"{n}={v:.6g}" for n, v in zip(self.kind.parameter_names, self.parameters)
        )
        return f"{self.name}: {self.kind.label} ({parts})"


def _initial_guess(
    kind: MaterialModelKind, strain: np.ndarray, stress: np.ndarray
) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
    """Starting point and bounds for the fit.

    Seeded from the secant modulus of the data, so the optimiser starts in the right
    order of magnitude rather than at an arbitrary value. Coefficients are bounded
    non-negative, which keeps the fit physically sensible (a negative C10 gives
    negative initial stiffness).
    """
    finite = (strain > 1.0e-6) & np.isfinite(stress)
    secant = float(np.median(stress[finite] / strain[finite])) if finite.any() else 1.0
    secant = max(secant, 1.0e-4)
    mu0 = secant / 3.0  # E approximately 3*mu0 for incompressible material

    if kind is MaterialModelKind.LINEAR_ELASTIC:
        return np.array([secant, 0.4995]), (np.array([1e-6, 0.0]), np.array([1e6, 0.4999]))
    if kind is MaterialModelKind.NEO_HOOKEAN:
        return np.array([mu0 / 2.0]), (np.array([1e-9]), np.array([1e6]))
    if kind is MaterialModelKind.MOONEY_RIVLIN:
        return (
            np.array([mu0 / 2.0 * 0.8, mu0 / 2.0 * 0.2]),
            (np.array([1e-9, 0.0]), np.array([1e6, 1e6])),
        )
    if kind is MaterialModelKind.OGDEN_1:
        return (
            np.array([mu0, 2.0]),
            (np.array([1e-9, 0.1]), np.array([1e6, 30.0])),
        )
    if kind is MaterialModelKind.OGDEN_2:
        return (
            np.array([mu0, 2.0, mu0 / 10.0, -2.0]),
            (np.array([1e-9, 0.1, 1e-9, -30.0]), np.array([1e6, 30.0, 1e6, -0.1])),
        )
    raise NotImplementedError(kind)  # pragma: no cover


def provisional_tpu(youngs_modulus_mpa: float = 12.0) -> HyperelasticModel:
    """A deliberately unvalidated placeholder, for exercising the workflow.

    This is **not** a model of TPU 90A. It is a Neo-Hookean solid with a round initial
    modulus, provided so the analysis pipeline can be run end to end before test data
    exists. Its provenance is UNVALIDATED_ASSUMPTION and it carries the assumed-material
    caveat permanently, so every force, stress and torque computed from it is marked
    unvalidated all the way into the exports.

    The default 12 MPa is an order-of-magnitude figure for a soft thermoplastic
    polyurethane and is not derived from the 90A hardness grade, because no defensible
    derivation exists. It is also not taken from the SUNLU sheet, which states no
    modulus at all. Replace it with a fit to a real tensile test; see
    ``docs/06-required-inputs.md`` item 7 for what to measure.
    """
    nu = 0.4995
    mu0 = youngs_modulus_mpa / (2.0 * (1.0 + nu))
    model = HyperelasticModel(
        kind=MaterialModelKind.NEO_HOOKEAN,
        parameters=(mu0 / 2.0,),
        name="TPU (PROVISIONAL - not calibrated)",
        poisson_ratio=nu,
        provenance=Provenance.UNVALIDATED_ASSUMPTION,
        caveats=(CAVEAT_ASSUMED_MATERIAL,),
        calibration_strain_range=None,
    )
    model.notes.append(
        "PROVISIONAL placeholder. Not a characterisation of TPU 90A and not derived "
        "from the hardness grade. Every result computed from it is unvalidated."
    )
    model.notes.append(
        "Replace by fitting HyperelasticModel.fit_uniaxial to a tensile test on a "
        "specimen printed with the same filament, printer, orientation and settings "
        "as the real part."
    )
    return model
