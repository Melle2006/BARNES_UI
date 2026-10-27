"""Body and point loads: gravity and tendon forces.

The unit trap, stated before anything else
-------------------------------------------

This project's canonical units are millimetres, newtons and megapascals. In that
system mass is **tonnes** and density is **tonnes per cubic millimetre**, because
1 N = 1 tonne * 1 mm / s^2. TPU at 1.2 g/cm^3 is therefore ``1.2e-9 t/mm^3``, and
gravity is ``9810 mm/s^2``.

Putting 1.2e-3 in as a density, which is what g/cm^3 and kg/m^3 both look like in
the wrong system, overstates every self-weight force by a factor of a million. The
result converges cleanly and is wrong. Risk R8, and the reason
:class:`GravityLoad` carries a constructor that takes the density in the unit a
datasheet states it in and does the conversion in one place.

Why gravity is worth modelling at all on a finger flexure
----------------------------------------------------------

Mostly it is not. A 0.3 g phalanx under gravity is about 3 mN, against restoring
torques that correspond to forces two orders of magnitude larger. The reason to
implement it is that it is the cheapest possible benchmark of a body load -- a
cantilever under its own weight has a closed-form tip deflection -- so it tests the
density path, the ``*DLOAD`` path and the unit system all at once, for a few seconds
of solver time. Whether gravity matters for a given design is then a question the
tool can answer rather than assume.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "GravityLoad",
    "PointLoad",
    "LoadError",
    "STANDARD_GRAVITY_MM_S2",
    "density_from_g_per_cm3",
]

#: Standard gravity in the project's units: 9.80665 m/s^2 expressed in mm/s^2.
STANDARD_GRAVITY_MM_S2 = 9806.65


class LoadError(ValueError):
    """A load that cannot be applied as specified."""


def density_from_g_per_cm3(value: float) -> float:
    """Convert g/cm^3, which is how a filament datasheet states it, to t/mm^3.

    1 g/cm^3 = 1000 kg/m^3 = 1e-9 tonne/mm^3.
    """
    if value <= 0.0:
        raise LoadError(f"Density must be positive, got {value} g/cm^3.")
    return value * 1.0e-9


@dataclass(frozen=True)
class GravityLoad:
    """A uniform body acceleration applied to an element set.

    ``direction`` need not be normalised; it is normalised here. ``magnitude`` is in
    mm/s^2 and defaults to standard gravity.

    ``density`` is in tonnes per cubic millimetre and has no default, deliberately.
    A default density would be an invented material property, which is the one thing
    this project refuses to do -- see risk R2. Use :func:`density_from_g_per_cm3` if
    the datasheet gives g/cm^3.
    """

    density: float
    direction: tuple[float, float, float] = (0.0, 0.0, -1.0)
    magnitude: float = STANDARD_GRAVITY_MM_S2
    element_set: str = "Eall"

    def __post_init__(self) -> None:
        if self.density <= 0.0:
            raise LoadError(
                f"Density must be positive, got {self.density} t/mm^3. If this looks "
                "like a reasonable number for g/cm^3, it is off by a factor of 1e9 -- "
                "use density_from_g_per_cm3()."
            )
        if self.density > 1.0e-7:
            raise LoadError(
                f"A density of {self.density:g} t/mm^3 is {self.density * 1e9:.1f} "
                "g/cm^3, denser than steel. This is almost certainly a unit error: "
                "the project works in mm, N, MPa, where density is tonnes per cubic "
                "millimetre and a polymer is around 1.2e-9."
            )
        if self.magnitude < 0.0:
            raise LoadError("Gravity magnitude must not be negative; flip direction.")
        norm = float(np.linalg.norm(self.direction))
        if norm < 1.0e-12:
            raise LoadError("Gravity direction is a zero vector.")

    @property
    def unit_direction(self) -> tuple[float, float, float]:
        vector = np.asarray(self.direction, dtype=float)
        vector = vector / np.linalg.norm(vector)
        return (float(vector[0]), float(vector[1]), float(vector[2]))

    @property
    def density_g_per_cm3(self) -> float:
        return self.density * 1.0e9

    def describe(self) -> str:
        x, y, z = self.unit_direction
        return (
            f"gravity {self.magnitude:.6g} mm/s^2 along ({x:.3f}, {y:.3f}, {z:.3f}) "
            f"on {self.element_set}, density {self.density:.4g} t/mm^3 "
            f"({self.density_g_per_cm3:.3f} g/cm^3)"
        )


@dataclass(frozen=True)
class PointLoad:
    """A concentrated force on a node set, used for tendon loading.

    The force is applied to *each* node in the set, which is CalculiX's own behaviour
    for ``*CLOAD`` on a set and is the thing most likely to surprise. Use
    ``total=True`` to divide the stated force among the nodes instead, which is
    almost always what is meant by "pull the tendon with 5 N".
    """

    node_set: str
    force: tuple[float, float, float]
    #: When True, ``force`` is the resultant and is split across the set's nodes.
    total: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if float(np.linalg.norm(self.force)) < 1.0e-15:
            raise LoadError(
                f"Point load on {self.node_set!r} is a zero vector. A load that does "
                "nothing is more likely a mistake than an intention."
            )

    def per_node(self, node_count: int) -> tuple[float, float, float]:
        if node_count <= 0:
            raise LoadError(
                f"Point load on {self.node_set!r}: the set has no nodes."
            )
        scale = 1.0 / node_count if self.total else 1.0
        return tuple(float(component * scale) for component in self.force)

    @property
    def magnitude(self) -> float:
        return float(np.linalg.norm(self.force))

    def describe(self) -> str:
        how = "total, split across the set" if self.total else "per node"
        return (
            f"{self.magnitude:.6g} N on {self.node_set} ({how})"
            + (f" -- {self.description}" if self.description else "")
        )
