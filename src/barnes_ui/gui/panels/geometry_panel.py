"""Geometry panel: solid tree, measured properties, warnings and units.

This is where Phase 1's output is presented. Three principles govern the layout, all
of them from the project's requirement that results be trustworthy rather than
merely impressive:

* every number shows its unit;
* every number shows its provenance tag;
* anything unconfirmed or invalid is visible without scrolling or expanding.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.cad.model import GeometryModel, SolidInfo, WarningSeverity
from ...core.provenance import Provenance
from ...core.units import LengthUnit, UnitConfidence, UnitSystem, format_quantity

logger = logging.getLogger(__name__)

__all__ = ["GeometryPanel"]

_SEVERITY_COLOURS = {
    WarningSeverity.INFO: "#4C8FBD",
    WarningSeverity.CAUTION: "#E8A33D",
    WarningSeverity.BLOCKING: "#D9534F",
}


class GeometryPanel(QWidget):
    """Shows what was imported and what was measured from it."""

    solid_visibility_changed = Signal(int, bool)
    solid_selected = Signal(int)
    unit_changed = Signal(object)  # LengthUnit

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: GeometryModel | None = None
        self._units = UnitSystem()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_source_box())
        layout.addWidget(self._build_unit_box())
        layout.addWidget(self._build_tree_box(), stretch=2)
        layout.addWidget(self._build_properties_box(), stretch=3)
        layout.addWidget(self._build_status_box(), stretch=1)

        self.clear()

    # -- construction ----------------------------------------------------------

    def _build_source_box(self) -> QWidget:
        box = QGroupBox("Source")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._file_label = QLabel("-")
        self._file_label.setWordWrap(True)
        self._format_label = QLabel("-")
        self._exactness_label = QLabel("-")
        self._exactness_label.setWordWrap(True)

        form.addRow("File:", self._file_label)
        form.addRow("Format:", self._format_label)
        form.addRow("Geometry:", self._exactness_label)
        return box

    def _build_unit_box(self) -> QWidget:
        """Unit interpretation and confirmation.

        Prominent on purpose. A model silently assumed to be in millimetres when it is
        in inches is wrong by 25.4 in every length and by 25.4 cubed in every volume,
        with nothing on screen to betray it. See risk R8.

        The combo sets how the file's stored coordinates are *interpreted*, not merely
        how they are displayed. Those two are deliberately not separated here, because
        a separate display unit on top of an unconfirmed source unit gives two places
        for a factor of 25.4 to hide instead of one.

        For STEP and IGES the control is read-only: those formats declare their unit,
        and OpenCASCADE has already converted the geometry to millimetres on import.
        Allowing a change there would apply a conversion that has already happened.
        """
        box = QGroupBox("Units")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Length unit:"))
        self._unit_combo = QComboBox()
        for unit in (
            LengthUnit.MILLIMETRE, LengthUnit.CENTIMETRE,
            LengthUnit.METRE, LengthUnit.INCH,
        ):
            self._unit_combo.addItem(f"{unit.symbol}", userData=unit)
        self._unit_combo.currentIndexChanged.connect(self._on_unit_selected)
        row.addWidget(self._unit_combo, stretch=1)

        self._confirm_button = QPushButton("Confirm")
        self._confirm_button.setToolTip(
            "Mark the unit as checked by a human. Until this is done the model is "
            "not considered ready for analysis."
        )
        self._confirm_button.clicked.connect(self._on_unit_confirmed)
        row.addWidget(self._confirm_button)
        layout.addLayout(row)

        self._unit_status = QLabel("-")
        self._unit_status.setWordWrap(True)
        layout.addWidget(self._unit_status)
        return box

    def _build_tree_box(self) -> QWidget:
        box = QGroupBox("Bodies")
        layout = QVBoxLayout(box)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Body", "Volume", "Valid"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree)
        return box

    def _build_properties_box(self) -> QWidget:
        box = QGroupBox("Measured properties")
        layout = QVBoxLayout(box)

        caption = QLabel(
            f"All values below are tagged "
            f"<b>{Provenance.GEOMETRIC_MEASUREMENT.label}</b> - read from the CAD "
            f"model, not estimated."
        )
        caption.setWordWrap(True)
        caption.setStyleSheet("color: #7FB069;")
        layout.addWidget(caption)

        self._properties = QTreeWidget()
        self._properties.setColumnCount(2)
        self._properties.setHeaderLabels(["Property", "Value"])
        self._properties.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._properties.setRootIsDecorated(False)
        self._properties.setAlternatingRowColors(True)
        layout.addWidget(self._properties)
        return box

    def _build_status_box(self) -> QWidget:
        box = QGroupBox("Validity and warnings")
        layout = QVBoxLayout(box)

        self._readiness = QLabel("-")
        self._readiness.setWordWrap(True)
        font = QFont()
        font.setBold(True)
        self._readiness.setFont(font)
        layout.addWidget(self._readiness)

        self._warnings = QTreeWidget()
        self._warnings.setColumnCount(1)
        self._warnings.setHeaderHidden(True)
        self._warnings.setWordWrap(True)
        layout.addWidget(self._warnings)
        return box

    # -- population ------------------------------------------------------------

    def clear(self) -> None:
        self._model = None
        self._file_label.setText("No model loaded")
        self._format_label.setText("-")
        self._exactness_label.setText("-")
        self._unit_status.setText("-")
        self._tree.clear()
        self._properties.clear()
        self._warnings.clear()
        self._readiness.setText("No model loaded.")
        self._readiness.setStyleSheet("")
        self._unit_combo.setEnabled(False)
        self._confirm_button.setEnabled(False)

    def show_model(self, model: GeometryModel) -> None:
        self._model = model
        self._units = UnitSystem(length=model.unit)

        self._file_label.setText(str(model.source_path.name))
        self._file_label.setToolTip(str(model.source_path))
        self._format_label.setText(model.source_format.label)

        if model.is_exact:
            self._exactness_label.setText("Exact B-rep - suitable for analysis")
            self._exactness_label.setStyleSheet("color: #7FB069;")
        else:
            self._exactness_label.setText(
                "Tessellated - curvature, bend radius and arc length are "
                "approximations. Not usable for analysis."
            )
            self._exactness_label.setStyleSheet("color: #E8A33D;")

        self._populate_units(model)
        self._populate_tree(model)
        self._populate_warnings(model)
        self._populate_readiness(model)

        if model.solids:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        else:
            self._show_model_summary(model)

    def _populate_units(self, model: GeometryModel) -> None:
        self._unit_combo.blockSignals(True)
        index = self._unit_combo.findData(model.unit)
        if index >= 0:
            self._unit_combo.setCurrentIndex(index)
        self._unit_combo.blockSignals(False)

        # A declared unit has already been applied by the kernel's reader. Offering to
        # change it would invite applying the same conversion twice.
        declared_by_file = model.declared_unit is not None and model.source_format.declares_units
        self._unit_combo.setEnabled(not declared_by_file)

        confidence = model.unit_confidence
        text = f"Unit is {confidence.description}."
        if declared_by_file:
            text += (
                f" The file declared {model.declared_unit.symbol} and the geometry "
                f"was converted to {model.unit.symbol} on import, so this cannot be "
                "changed here."
            )
        else:
            text += (
                " Changing this reinterprets the file's stored coordinates; it does "
                "not rescale them for display only."
            )
        self._unit_status.setText(text)

        if confidence.is_trustworthy:
            self._unit_status.setStyleSheet("color: #7FB069;")
            self._confirm_button.setEnabled(False)
        else:
            self._unit_status.setStyleSheet("color: #E8A33D; font-weight: bold;")
            self._confirm_button.setEnabled(True)

    def _populate_tree(self, model: GeometryModel) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        for solid in model.solids:
            item = QTreeWidgetItem([
                solid.name,
                format_quantity(solid.volume, self._units.volume_symbol, 5),
                "yes" if solid.is_valid else "NO",
            ])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, solid.index)
            if not solid.is_valid:
                item.setForeground(2, QBrush(QColor(_SEVERITY_COLOURS[WarningSeverity.BLOCKING])))
            self._tree.addTopLevelItem(item)
        self._tree.blockSignals(False)

    def _populate_warnings(self, model: GeometryModel) -> None:
        self._warnings.clear()
        if not model.warnings:
            item = QTreeWidgetItem(["No problems found."])
            item.setForeground(0, QBrush(QColor("#7FB069")))
            self._warnings.addTopLevelItem(item)
            return

        order = [WarningSeverity.BLOCKING, WarningSeverity.CAUTION, WarningSeverity.INFO]
        for severity in order:
            for warning in model.warnings_of(severity):
                parent = QTreeWidgetItem([f"[{severity.value.upper()}] {warning.title}"])
                parent.setForeground(0, QBrush(QColor(_SEVERITY_COLOURS[severity])))
                detail = QTreeWidgetItem([warning.detail])
                detail.setToolTip(0, warning.detail)
                parent.addChild(detail)
                self._warnings.addTopLevelItem(parent)
                parent.setExpanded(severity is WarningSeverity.BLOCKING)

    def _populate_readiness(self, model: GeometryModel) -> None:
        if model.is_analysis_ready:
            self._readiness.setText("Ready for analysis.")
            self._readiness.setStyleSheet("color: #7FB069;")
            return
        reasons = model.analysis_readiness_reasons()
        self._readiness.setText(
            "NOT ready for analysis:\n" + "\n".join(f"  - {r}" for r in reasons)
        )
        self._readiness.setStyleSheet("color: #E8A33D;")

    # -- property display ------------------------------------------------------

    def _show_solid_properties(self, solid: SolidInfo) -> None:
        # Stored coordinates are already in the model's unit, so the values are shown
        # as they are and only the symbols come from the unit system. There is no
        # conversion step here, by design -- see _build_unit_box.
        self._properties.clear()
        units = self._units
        rows: list[tuple[str, str]] = []

        box = solid.bounding_box
        dx, dy, dz = box.size
        cx, cy, cz = box.centre
        mx, my, mz = solid.centre_of_mass
        L = units.length_symbol

        rows.append(("Name", solid.name))
        rows.append(("Volume", format_quantity(solid.volume, units.volume_symbol)))
        rows.append((
            "Surface area",
            format_quantity(solid.surface_area, units.area_symbol),
        ))
        rows.append(("Bounding box X", format_quantity(dx, L)))
        rows.append(("Bounding box Y", format_quantity(dy, L)))
        rows.append(("Bounding box Z", format_quantity(dz, L)))
        rows.append((
            "Smallest extent",
            format_quantity(box.smallest_dimension, L),
        ))
        rows.append(("Diagonal", format_quantity(box.diagonal, L)))
        rows.append(("Box centre", f"({cx:.5g}, {cy:.5g}, {cz:.5g}) {L}"))
        rows.append(("Centre of mass", f"({mx:.5g}, {my:.5g}, {mz:.5g}) {L}"))

        counts = solid.counts
        rows.append(("Faces", str(counts.faces)))
        rows.append(("Edges", str(counts.edges)))
        rows.append(("Vertices", str(counts.vertices)))
        rows.append(("Shells", str(counts.shells)))
        rows.append(("Topology valid", "yes" if solid.is_valid else "NO"))

        for name, value in rows:
            self._properties.addTopLevelItem(QTreeWidgetItem([name, value]))

        if solid.validity_detail:
            item = QTreeWidgetItem(["Validity detail", solid.validity_detail])
            item.setToolTip(1, solid.validity_detail)
            self._properties.addTopLevelItem(item)

        # Centre of mass is a geometric centroid at unit density, not a physical
        # centre of mass. Saying so avoids an easy misreading.
        note = QTreeWidgetItem([
            "Note",
            "Centre of mass is the centroid at uniform density. No material density "
            "is applied, so no mass is reported.",
        ])
        note.setForeground(1, QBrush(QColor("#9AA3AD")))
        self._properties.addTopLevelItem(note)

    def _show_model_summary(self, model: GeometryModel) -> None:
        self._properties.clear()
        units = self._units
        rows = [
            ("Bodies", str(model.solid_count)),
            ("Total volume",
             format_quantity(model.total_volume, units.volume_symbol)),
        ]
        box = model.overall_bounding_box
        if box:
            dx, dy, dz = box.size
            rows.append((
                "Overall bounding box",
                f"{dx:.5g} x {dy:.5g} x {dz:.5g} {units.length_symbol}",
            ))
        for note in model.loader_notes:
            rows.append(("Loader note", note))
        for name, value in rows:
            self._properties.addTopLevelItem(QTreeWidgetItem([name, value]))

    # -- signals ---------------------------------------------------------------

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        self.solid_visibility_changed.emit(int(index), visible)

    def _on_selection_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None or self._model is None:
            return
        index = current.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        index = int(index)
        if 0 <= index < len(self._model.solids):
            self._show_solid_properties(self._model.solids[index])
            self.solid_selected.emit(index)

    def _on_unit_selected(self, _index: int) -> None:
        if self._model is None:
            return
        unit = self._unit_combo.currentData()
        if unit is None:
            return
        # Reinterpret the stored coordinates as being in this unit. Choosing from the
        # list is an explicit human statement, so the confidence is raised to USER_SET.
        self._model.unit = unit
        self._model.unit_confidence = UnitConfidence.USER_SET
        self._units = UnitSystem(length=unit)
        self._refresh_after_unit_change()
        self.unit_changed.emit(unit)

    def _on_unit_confirmed(self) -> None:
        if self._model is None:
            return
        self._model.unit_confidence = UnitConfidence.USER_SET
        self._refresh_after_unit_change()

    def _refresh_after_unit_change(self) -> None:
        assert self._model is not None
        current = self._tree.currentItem()
        self._populate_units(self._model)
        self._populate_tree(self._model)
        self._populate_readiness(self._model)
        if current is not None:
            index = current.data(0, Qt.ItemDataRole.UserRole)
            if index is not None and 0 <= int(index) < len(self._model.solids):
                self._show_solid_properties(self._model.solids[int(index)])
                item = self._tree.topLevelItem(int(index))
                if item is not None:
                    self._tree.setCurrentItem(item)
