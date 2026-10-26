"""Material model tests.

Guards risk R2: material characterisation is the accuracy ceiling for every absolute
force this project reports.
"""

from __future__ import annotations

import numpy as np
import pytest

from barnes_ui.core.material.models import (
    CAVEAT_DATASHEET_DERIVED,
    CAVEAT_OUTSIDE_CALIBRATION,
    HyperelasticModel,
    MaterialModelKind,
    provisional_tpu,
)
from barnes_ui.core.provenance import CAVEAT_ASSUMED_MATERIAL, Provenance


class TestInitialModuli:
    """The small-strain limits must be internally consistent across model families."""

    def test_neo_hookean_shear_modulus(self) -> None:
        model = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (1.5,))
        assert model.initial_shear_modulus == pytest.approx(3.0)  # mu0 = 2*C10

    def test_mooney_rivlin_shear_modulus(self) -> None:
        model = HyperelasticModel(MaterialModelKind.MOONEY_RIVLIN, (1.0, 0.5))
        assert model.initial_shear_modulus == pytest.approx(3.0)  # 2*(C10+C01)

    def test_ogden_shear_modulus(self) -> None:
        # mu0 = 0.5 * sum(mu_i * alpha_i) = 0.5 * (4.0 * 2.0) = 4.0
        model = HyperelasticModel(MaterialModelKind.OGDEN_1, (4.0, 2.0))
        assert model.initial_shear_modulus == pytest.approx(4.0)

    def test_youngs_modulus_from_shear(self) -> None:
        """E = 2*mu0*(1+nu); for near-incompressible this is close to 3*mu0."""
        model = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (1.0,))
        expected = 2.0 * 2.0 * (1.0 + model.poisson_ratio)
        assert model.initial_youngs_modulus == pytest.approx(expected)
        assert model.initial_youngs_modulus == pytest.approx(3.0 * 2.0, rel=1e-3)

    def test_linear_elastic_returns_its_own_modulus(self) -> None:
        model = HyperelasticModel(MaterialModelKind.LINEAR_ELASTIC, (12.0, 0.3))
        assert model.initial_youngs_modulus == pytest.approx(12.0)
        assert model.poisson_ratio == pytest.approx(0.3)

    def test_wrong_parameter_count_raises(self) -> None:
        with pytest.raises(ValueError, match="needs 2 parameter"):
            HyperelasticModel(MaterialModelKind.MOONEY_RIVLIN, (1.0,))


class TestUniaxialResponse:
    def test_zero_stress_at_unit_stretch(self) -> None:
        """An undeformed hyperelastic solid must carry no stress."""
        for kind, params in [
            (MaterialModelKind.NEO_HOOKEAN, (2.0,)),
            (MaterialModelKind.MOONEY_RIVLIN, (1.5, 0.5)),
            (MaterialModelKind.OGDEN_1, (4.0, 2.0)),
            (MaterialModelKind.OGDEN_2, (4.0, 2.0, 0.4, -2.0)),
        ]:
            model = HyperelasticModel(kind, params)
            assert float(model.uniaxial_engineering_stress(1.0)) == pytest.approx(
                0.0, abs=1e-9
            ), f"{kind.label} is not stress-free at lambda = 1"

    @pytest.mark.parametrize(
        "kind,params",
        [
            (MaterialModelKind.NEO_HOOKEAN, (2.0,)),
            (MaterialModelKind.MOONEY_RIVLIN, (1.5, 0.5)),
            (MaterialModelKind.OGDEN_1, (4.0, 2.0)),
        ],
    )
    def test_secant_modulus_tends_to_youngs_modulus(self, kind, params) -> None:
        """P/strain must approach E as strain approaches zero.

        This is the check that ties the hyperelastic parameters to the linear modulus
        the reduced-order beam model consumes. If it fails, the beam model is being fed
        a modulus inconsistent with the material it claims to represent.
        """
        model = HyperelasticModel(kind, params)
        strain = 1.0e-5
        secant = float(model.uniaxial_engineering_stress(1.0 + strain)) / strain
        assert secant == pytest.approx(model.initial_youngs_modulus, rel=1e-3)

    def test_neo_hookean_matches_closed_form(self) -> None:
        """P = 2*C10*(lam - lam^-2), checked against hand evaluation."""
        model = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        lam = 1.5
        expected = 2.0 * 2.0 * (lam - lam**-2)
        assert float(model.uniaxial_engineering_stress(lam)) == pytest.approx(expected)

    def test_true_stress_is_engineering_times_stretch(self) -> None:
        model = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        lam = np.array([1.2, 1.8])
        assert np.allclose(
            model.uniaxial_true_stress(lam),
            model.uniaxial_engineering_stress(lam) * lam,
        )

    def test_stress_increases_with_stretch(self) -> None:
        model = HyperelasticModel(MaterialModelKind.MOONEY_RIVLIN, (1.5, 0.5))
        lam = np.linspace(1.0, 3.0, 40)
        stress = model.uniaxial_engineering_stress(lam)
        assert np.all(np.diff(stress) > 0)

    def test_non_positive_stretch_raises(self) -> None:
        model = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        with pytest.raises(ValueError, match="must be positive"):
            model.uniaxial_engineering_stress(0.0)


class TestFitting:
    def test_recovers_known_parameters(self) -> None:
        """Fit synthetic data generated from a known model and get it back."""
        truth = HyperelasticModel(MaterialModelKind.MOONEY_RIVLIN, (1.20, 0.30))
        strain = np.linspace(0.01, 1.0, 40)
        stress = truth.uniaxial_engineering_stress(1.0 + strain)

        fitted = HyperelasticModel.fit_uniaxial(
            strain, stress, kind=MaterialModelKind.MOONEY_RIVLIN
        )
        assert fitted.parameters[0] == pytest.approx(1.20, rel=1e-3)
        assert fitted.parameters[1] == pytest.approx(0.30, rel=1e-3)

    def test_recovers_neo_hookean(self) -> None:
        truth = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.5,))
        strain = np.linspace(0.01, 0.8, 30)
        stress = truth.uniaxial_engineering_stress(1.0 + strain)
        fitted = HyperelasticModel.fit_uniaxial(
            strain, stress, kind=MaterialModelKind.NEO_HOOKEAN
        )
        assert fitted.parameters[0] == pytest.approx(2.5, rel=1e-4)

    def test_records_the_calibration_range(self) -> None:
        strain = np.linspace(0.02, 0.60, 20)
        truth = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        fitted = HyperelasticModel.fit_uniaxial(
            strain, truth.uniaxial_engineering_stress(1.0 + strain)
        )
        low, high = fitted.calibration_strain_range
        assert low == pytest.approx(0.02)
        assert high == pytest.approx(0.60)

    def test_flags_extrapolation_beyond_the_fitted_range(self) -> None:
        """The headline protection against trusting a fit outside its data."""
        strain = np.linspace(0.02, 0.30, 20)
        truth = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        fitted = HyperelasticModel.fit_uniaxial(
            strain, truth.uniaxial_engineering_stress(1.0 + strain)
        )
        assert fitted.is_within_calibration(0.20)
        assert not fitted.is_within_calibration(0.90)
        assert CAVEAT_OUTSIDE_CALIBRATION in fitted.caveats_for_strain(0.90)
        assert CAVEAT_OUTSIDE_CALIBRATION not in fitted.caveats_for_strain(0.20)

    def test_fit_is_not_promoted_to_validated(self) -> None:
        """Reproducing the test you were fitted to is not independent validation."""
        strain = np.linspace(0.02, 0.5, 20)
        truth = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        fitted = HyperelasticModel.fit_uniaxial(
            strain, truth.uniaxial_engineering_stress(1.0 + strain)
        )
        assert fitted.provenance is Provenance.ANALYTICAL_ESTIMATE
        assert fitted.provenance < Provenance.EXPERIMENTALLY_VALIDATED

    def test_datasheet_source_is_recorded_as_a_caveat(self) -> None:
        strain = np.linspace(0.02, 0.5, 20)
        truth = HyperelasticModel(MaterialModelKind.NEO_HOOKEAN, (2.0,))
        fitted = HyperelasticModel.fit_uniaxial(
            strain, truth.uniaxial_engineering_stress(1.0 + strain),
            from_datasheet=True,
        )
        assert CAVEAT_DATASHEET_DERIVED in fitted.caveats

    def test_too_few_points_raises(self) -> None:
        with pytest.raises(ValueError, match="only 1 data point"):
            HyperelasticModel.fit_uniaxial(
                [0.1], [1.0], kind=MaterialModelKind.MOONEY_RIVLIN
            )

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            HyperelasticModel.fit_uniaxial([0.1, 0.2], [1.0])


class TestProvisionalMaterial:
    """The provisional placeholder must be impossible to mistake for real data."""

    def test_is_tagged_as_an_unvalidated_assumption(self) -> None:
        model = provisional_tpu()
        assert model.provenance is Provenance.UNVALIDATED_ASSUMPTION

    def test_carries_the_assumed_material_caveat(self) -> None:
        assert CAVEAT_ASSUMED_MATERIAL in provisional_tpu().caveats

    def test_is_never_within_calibration(self) -> None:
        """An uncalibrated model is outside its validity range everywhere."""
        model = provisional_tpu()
        assert model.calibration_strain_range is None
        for strain in (0.0, 0.01, 0.5, 2.0):
            assert not model.is_within_calibration(strain)

    def test_name_announces_that_it_is_provisional(self) -> None:
        assert "PROVISIONAL" in provisional_tpu().name

    def test_honours_the_requested_modulus(self) -> None:
        for E in (5.0, 12.0, 40.0):
            assert provisional_tpu(E).initial_youngs_modulus == pytest.approx(E)

    def test_tagged_modulus_carries_provenance_and_caveats(self) -> None:
        tagged = provisional_tpu().tagged_youngs_modulus()
        assert tagged.unit == "MPa"
        assert tagged.provenance is Provenance.UNVALIDATED_ASSUMPTION
        assert CAVEAT_ASSUMED_MATERIAL in tagged.caveats
