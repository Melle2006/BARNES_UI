"""Unit handling.

The application uses one canonical internal unit system and converts only at the
boundaries -- when reading a file, and when formatting a value for display or export.
Mixing unit systems in the middle of a calculation is risk R8 in the risk register, and
it is the kind of error that produces answers wrong by a factor of 1000 while looking
entirely reasonable.

Canonical internal units
------------------------

    length          millimetre      mm
    force           newton          N
    stress          megapascal      MPa     (= N/mm^2)
    moment/torque   newton-mm       N.mm
    angle           radian          rad     (degrees only at the UI boundary)
    density         tonne/mm^3              (the consistent partner of mm/N/MPa)

This is the standard mm/N/MPa consistent set used by most FE codes, which matters
because it means no conversion is needed when writing a solver input deck. The slightly
surprising density unit is a consequence of insisting on consistency: if length is mm
and force is N, then mass must be tonnes for F = ma to hold without a conversion factor.

Angles are radians everywhere inside ``core``. The GUI converts to degrees for display,
because engineers think in degrees, but no calculation ever sees a degree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "LengthUnit",
    "UnitConfidence",
    "CANONICAL_LENGTH",
    "convert_length",
    "scale_factor_to_mm",
    "format_quantity",
    "deg_to_rad",
    "rad_to_deg",
    "UnitSystem",
]


class LengthUnit(Enum):
    """A length unit, with its size expressed in millimetres.

    The value is the number of millimetres in one of this unit, which makes
    conversion a single multiplication and makes the table self-documenting.
    """

    NANOMETRE = ("nm", 1e-6)
    MICROMETRE = ("um", 1e-3)
    MILLIMETRE = ("mm", 1.0)
    CENTIMETRE = ("cm", 10.0)
    DECIMETRE = ("dm", 100.0)
    METRE = ("m", 1000.0)
    KILOMETRE = ("km", 1e6)
    INCH = ("in", 25.4)
    FOOT = ("ft", 304.8)
    MIL = ("mil", 0.0254)  # thousandth of an inch, occasionally seen in DXF

    def __init__(self, symbol: str, millimetres: float) -> None:
        self.symbol = symbol
        self.millimetres = millimetres

    @classmethod
    def from_symbol(cls, symbol: str) -> "LengthUnit":
        """Look up a unit by its symbol, case-insensitively.

        Raises ValueError rather than guessing, because a guess here is a silent
        scaling error downstream.
        """
        wanted = symbol.strip().lower()
        for unit in cls:
            if unit.symbol == wanted:
                return unit
        # A few spellings that turn up in CAD file headers and user input.
        aliases = {
            "millimetre": cls.MILLIMETRE,
            "millimeter": cls.MILLIMETRE,
            "milli": cls.MILLIMETRE,
            "centimetre": cls.CENTIMETRE,
            "centimeter": cls.CENTIMETRE,
            "metre": cls.METRE,
            "meter": cls.METRE,
            "inch": cls.INCH,
            "inches": cls.INCH,
            "foot": cls.FOOT,
            "feet": cls.FOOT,
            "micron": cls.MICROMETRE,
            "micrometre": cls.MICROMETRE,
            "micrometer": cls.MICROMETRE,
        }
        if wanted in aliases:
            return aliases[wanted]
        raise ValueError(f"Unrecognised length unit: {symbol!r}")

    def __str__(self) -> str:
        return self.symbol


#: Every length inside ``core`` is in this unit unless a docstring says otherwise.
CANONICAL_LENGTH = LengthUnit.MILLIMETRE


class UnitConfidence(Enum):
    """How much the recorded unit of a geometry model can be trusted.

    This exists because the three cases genuinely differ and conflating them is a real
    source of error:

    DECLARED
        The file stated its unit. STEP and IGES both carry an explicit unit declaration
        in their header, so this is read, not inferred, and can be relied on.

    ASSUMED
        The format carries no unit at all -- STL is the common case, and most meshes in
        general. The application has picked a default so that something can be
        displayed, but the number could be wrong by a factor of 25.4 or 1000 and nothing
        in the file would reveal it. Values stay flagged until a human confirms.

    USER_SET
        A person looked at it and said what the unit is. Treated as authoritative.
    """

    DECLARED = "declared"
    ASSUMED = "assumed"
    USER_SET = "user_set"

    @property
    def is_trustworthy(self) -> bool:
        """True when the unit came from the file or from a human, not from a default."""
        return self is not UnitConfidence.ASSUMED

    @property
    def description(self) -> str:
        return {
            UnitConfidence.DECLARED: "declared in the file header",
            UnitConfidence.ASSUMED: "assumed - NOT declared by the file, please confirm",
            UnitConfidence.USER_SET: "set by the user",
        }[self]


def scale_factor_to_mm(unit: LengthUnit) -> float:
    """Multiplier that converts a length in ``unit`` into millimetres."""
    return unit.millimetres


def convert_length(value: float, from_unit: LengthUnit, to_unit: LengthUnit) -> float:
    """Convert a length between units.

    Goes via millimetres rather than holding an N-by-N conversion table, which keeps the
    number of places a wrong constant could hide down to one per unit.
    """
    return value * from_unit.millimetres / to_unit.millimetres


def deg_to_rad(degrees: float) -> float:
    return degrees * math.pi / 180.0


def rad_to_deg(radians: float) -> float:
    return radians * 180.0 / math.pi


def format_quantity(value: float, unit: str, significant: int = 6) -> str:
    """Render a number with its unit for display.

    Switches to scientific notation at the extremes, where fixed-point would either lose
    all the information or run to twenty characters. Units are never omitted: a bare
    number in an engineering UI is an invitation to misread it.
    """
    if value is None:
        return f"- {unit}"
    magnitude = abs(value)
    if magnitude != 0 and (magnitude < 1e-4 or magnitude >= 1e7):
        text = f"{value:.{significant - 1}e}"
    else:
        text = f"{value:.{significant}g}"
    return f"{text} {unit}"


@dataclass(frozen=True)
class UnitSystem:
    """The unit symbols used for display and export.

    Only the length unit is configurable at present. Force and stress are fixed at N and
    MPa because changing them would desynchronise the solver decks, which are written in
    the consistent mm/N/MPa set. Derived symbols are computed from the length unit so
    that an area always reads as the square of whatever length unit is in force.
    """

    length: LengthUnit = CANONICAL_LENGTH

    @property
    def length_symbol(self) -> str:
        return self.length.symbol

    @property
    def area_symbol(self) -> str:
        return f"{self.length.symbol}^2"

    @property
    def volume_symbol(self) -> str:
        return f"{self.length.symbol}^3"

    @property
    def force_symbol(self) -> str:
        return "N"

    @property
    def stress_symbol(self) -> str:
        return "MPa"

    @property
    def moment_symbol(self) -> str:
        return f"N.{self.length.symbol}"

    @property
    def translational_stiffness_symbol(self) -> str:
        return f"N/{self.length.symbol}"

    @property
    def rotational_stiffness_symbol(self) -> str:
        return f"N.{self.length.symbol}/rad"

    def from_canonical_length(self, value_mm: float) -> float:
        """Convert a canonical (mm) length into this system's display unit."""
        return convert_length(value_mm, CANONICAL_LENGTH, self.length)

    def from_canonical_area(self, value_mm2: float) -> float:
        factor = CANONICAL_LENGTH.millimetres / self.length.millimetres
        return value_mm2 * factor**2

    def from_canonical_volume(self, value_mm3: float) -> float:
        factor = CANONICAL_LENGTH.millimetres / self.length.millimetres
        return value_mm3 * factor**3
