"""Data structures for an imported assembly.

An assembly is a tree of components, each with a name, a placement, and -- at the
leaves -- geometry. Everything here is plain data with no OpenCASCADE types in the
public surface except ``Component.shape``, which follows the same convention as
``cad.model.SolidInfo.shape``: typed loosely so this module imports without the kernel.

Why placements are tracked explicitly
-------------------------------------

OpenCASCADE's ordinary STEP reader returns one shape with every component's placement
already applied. That is the right answer for a single part and the wrong one for an
assembly: the component tree, the component names and the individual placements have
all been flattened away, and with them any chance of saying "the distal phalanx is
here, relative to the proximal one". The XCAF reader keeps them, and this module is
where they are kept afterwards.

A placement here is always **world**: the product of every transform from the root down
to the component. Storing the composed transform rather than the local one means a
caller never has to walk the tree to place a solid, which is the operation that
actually gets done, over and over, during an interference sweep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from ..cad.model import BoundingBox
from ..units import LengthUnit, UnitConfidence

__all__ = [
    "Placement",
    "Component",
    "Assembly",
]


@dataclass(frozen=True)
class Placement:
    """A rigid-body transform: rotate, then translate.

    Stored as a 3x3 rotation and a 3-vector rather than a 4x4, because that is what it
    is, and because a 4x4 invites someone to put a scale factor in it. A scaled
    component is not a placement -- it is a different part -- and silently accepting
    one would be exactly the kind of distortion risk R5 is about.
    """

    rotation: tuple[tuple[float, float, float], ...] = (
        (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    )
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @classmethod
    def identity(cls) -> "Placement":
        return cls()

    @classmethod
    def from_matrix(cls, matrix: Sequence[Sequence[float]]) -> "Placement":
        """Build from a 3x4 or 4x4 row-major matrix.

        Raises if the rotation block is not orthonormal to within 1e-9. A STEP file can
        legitimately contain a scaled or mirrored instance; this project cannot
        meaningfully analyse one, so it refuses rather than carrying a silent factor.
        """
        m = np.asarray(matrix, dtype=float)
        if m.shape not in ((3, 4), (4, 4)):
            raise ValueError(f"Expected a 3x4 or 4x4 matrix, got shape {m.shape}")
        rotation = m[:3, :3]
        residual = rotation.T @ rotation - np.eye(3)
        if np.max(np.abs(residual)) > 1.0e-9:
            raise ValueError(
                "The transform's rotation block is not orthonormal "
                f"(worst deviation {np.max(np.abs(residual)):.3g}), so it carries a "
                "scale or shear. A scaled component instance cannot be analysed as a "
                "placement of the same part."
            )
        if np.linalg.det(rotation) < 0.0:
            raise ValueError(
                "The transform is a mirror (negative determinant). A mirrored "
                "instance is a different part, not a placement of this one."
            )
        return cls(
            rotation=tuple(tuple(float(x) for x in row) for row in rotation),
            translation=tuple(float(x) for x in m[:3, 3]),
        )

    @property
    def matrix(self) -> np.ndarray:
        """4x4 homogeneous form, for composing and for the viewport."""
        m = np.eye(4)
        m[:3, :3] = np.asarray(self.rotation, dtype=float)
        m[:3, 3] = np.asarray(self.translation, dtype=float)
        return m

    @property
    def is_identity(self) -> bool:
        return bool(np.allclose(self.matrix, np.eye(4), atol=1.0e-12))

    def compose(self, inner: "Placement") -> "Placement":
        """``self`` applied after ``inner``: the placement of a child of ``self``."""
        return Placement.from_matrix(self.matrix @ inner.matrix)

    def inverse(self) -> "Placement":
        rotation = np.asarray(self.rotation, dtype=float)
        inverse_rotation = rotation.T
        m = np.eye(4)
        m[:3, :3] = inverse_rotation
        m[:3, 3] = -inverse_rotation @ np.asarray(self.translation, dtype=float)
        return Placement.from_matrix(m)

    def apply_point(self, point: Sequence[float]) -> tuple[float, float, float]:
        p = np.asarray(point, dtype=float)
        out = np.asarray(self.rotation, dtype=float) @ p + np.asarray(self.translation)
        return (float(out[0]), float(out[1]), float(out[2]))

    def apply_direction(self, direction: Sequence[float]) -> tuple[float, float, float]:
        """Rotate a direction. Translation does not apply to a direction."""
        out = np.asarray(self.rotation, dtype=float) @ np.asarray(direction, dtype=float)
        return (float(out[0]), float(out[1]), float(out[2]))

    def max_point_deviation(self, other: "Placement", radius: float) -> float:
        """Worst positional disagreement with ``other`` over a sphere of ``radius``.

        Comparing two placements by their translations alone misses a rotation error,
        which matters more the further a point is from the origin. This bounds the
        difference over everything inside ``radius``, which is the honest way to say
        "these two placements agree to better than 0.01 mm".
        """
        delta_rotation = (
            np.asarray(self.rotation, dtype=float)
            - np.asarray(other.rotation, dtype=float)
        )
        delta_translation = (
            np.asarray(self.translation, dtype=float)
            - np.asarray(other.translation, dtype=float)
        )
        # ||dR p + dt|| <= ||dR||_2 * r + ||dt||
        spectral = float(np.linalg.norm(delta_rotation, 2))
        return spectral * float(radius) + float(np.linalg.norm(delta_translation))

    def as_dict(self) -> dict[str, Any]:
        return {
            "rotation": [list(row) for row in self.rotation],
            "translation": list(self.translation),
        }


@dataclass
class Component:
    """One node of the assembly tree.

    A component either has geometry (a leaf, a part instance) or children (a
    subassembly), and occasionally both. ``placement`` is in world coordinates, already
    composed down the tree.
    """

    index: int
    name: str
    placement: Placement
    #: Path of names from the root, e.g. ``("hand", "index", "distal_phalanx")``.
    path: tuple[str, ...] = ()
    #: Positioned ``TopoDS_Shape`` for a leaf; ``None`` for a pure subassembly node.
    shape: Any = None
    children: list["Component"] = field(default_factory=list)
    volume: float = 0.0
    bounding_box: BoundingBox | None = None
    visible: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def has_geometry(self) -> bool:
        return self.shape is not None

    @property
    def qualified_name(self) -> str:
        return "/".join(self.path) if self.path else self.name

    def walk(self) -> Iterator["Component"]:
        """Depth-first traversal including self."""
        yield self
        for child in self.children:
            yield from child.walk()

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "path": list(self.path),
            "placement": self.placement.as_dict(),
            "has_geometry": self.has_geometry,
            "volume": self.volume,
            "bounding_box": self.bounding_box.as_dict() if self.bounding_box else None,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass
class Assembly:
    """An imported assembly: its tree, its units and what went wrong reading it."""

    source_path: Path
    unit: LengthUnit
    unit_confidence: UnitConfidence
    roots: list[Component] = field(default_factory=list)
    declared_unit: LengthUnit | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.source_path.stem

    def components(self) -> list[Component]:
        """Every node, depth-first."""
        return [c for root in self.roots for c in root.walk()]

    def parts(self) -> list[Component]:
        """Only the nodes that carry geometry."""
        return [c for c in self.components() if c.has_geometry]

    @property
    def part_count(self) -> int:
        return len(self.parts())

    @property
    def total_volume(self) -> float:
        return sum(c.volume for c in self.parts())

    def find(self, qualified_name: str) -> Component | None:
        for component in self.components():
            if component.qualified_name == qualified_name:
                return component
        return None

    def by_index(self, index: int) -> Component:
        for component in self.components():
            if component.index == index:
                return component
        raise KeyError(f"No component with index {index}")

    @property
    def overall_bounding_box(self) -> BoundingBox | None:
        boxes = [c.bounding_box for c in self.parts() if c.bounding_box]
        if not boxes:
            return None
        box = boxes[0]
        for other in boxes[1:]:
            box = box.merged_with(other)
        return box

    def tree_text(self) -> str:
        """Indented listing, for the component tree and for test output."""
        lines: list[str] = []

        def emit(component: Component, depth: int) -> None:
            marker = "*" if component.has_geometry else "+"
            suffix = f"  {component.volume:.4g} mm^3" if component.has_geometry else ""
            lines.append(f"{'  ' * depth}{marker} {component.name}{suffix}")
            for child in component.children:
                emit(child, depth + 1)

        for root in self.roots:
            emit(root, 0)
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        box = self.overall_bounding_box
        return {
            "source_path": str(self.source_path),
            "unit": self.unit.symbol,
            "unit_confidence": self.unit_confidence.value,
            "declared_unit": self.declared_unit.symbol if self.declared_unit else None,
            "part_count": self.part_count,
            "total_volume": self.total_volume,
            "overall_bounding_box": box.as_dict() if box else None,
            "roots": [r.as_dict() for r in self.roots],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }
