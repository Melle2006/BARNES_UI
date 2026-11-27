"""Parameter ranges to test for every TPU joint design: one Excel sheet per design.

    python3 scripts/make_parameter_ranges_workbook.py

Writes results/TPU_joint_parameter_ranges.xlsx. For every design: each parameter, the values the
project already swept (exact, from the build scripts named in the "source" column), a suggested
range for new runs (min, max, step, or a value set) with the reason, which ones are fixed by the
finger, how they scale per joint, and the bending angles and load cases to run.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

OUT = Path(__file__).resolve().parents[1] / "results" / "TPU_joint_parameter_ranges.xlsx"

HEAD = PatternFill("solid", fgColor="DDE6F0")
SEL = PatternFill("solid", fgColor="E2F0D9")
FIX = PatternFill("solid", fgColor="EEEEEE")
SEC = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BBBBBB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

COLS = ["Parameter", "Symbol", "Unit", "Swept in the project (exact)", "Selected / printed",
        "Suggested min", "Suggested max", "Step (or value set)", "Fixed by the finger?",
        "Per-joint scaling", "Limit / reason", "Source"]
WIDTHS = [30, 9, 8, 30, 18, 10, 10, 16, 12, 22, 46, 34]

GRADE = "PIP value; MCP x1.2727, DIP x0.8182"
FAM = "TYPE B/build_flexure_families.py"
R2 = "TYPE B/round2/build_round2.py"

# angles and loads shared by the Type B designs
TYPEB_CASES = [
    ["Bending angle (displacement-driven)", "theta", "deg", "round 1: to collar contact or 20 % strain; round 2 target MCP 90, PIP 100, DIP 80",
     "", 0, 100, "5 (1 near the limit)", "", "PIP 0-100, MCP 0-90, DIP 0-80", "stop at collar contact or 20 % peak strain, whichever first", R2 + " (TARGET_FLEX_DEG)"],
    ["Tendon force (force-driven)", "T", "N", "round 2: up to the servo limit 47 N at 0, 30, 60 deg", "", 0, 47, "2.5 (or 5, 10, 20, 30, 47)", "",
     "same at every joint", "47 N = servo limit; also the buckling / squash check", "TYPE B/round2/fea_round2.py"],
    ["Angle held while the tendon load is applied", "theta_T", "deg", "0, 30, 60", "", "", "", "value set: 0, 30, 60", "", "", "the three angles of rig step 2", "docs/12 Part 2"],
    ["Fingertip load at the 44.8 mm hook", "W", "N", "rig step 2: 50, 100, 200, 300, 500 g", "", 0.49, 4.91,
     "value set: 0.49, 0.98, 1.96, 2.94, 4.91", "", "", "44.8 mm = PIP to fingertip", "docs/12 Part 2"],
    ["Side load for twist (pinch)", "F_side", "N", "1 N, 5 mm off the axis", "", "", "", "value set: 1 N at 5 mm", "", "", "twist angle is a ranking criterion", "TYPE B/analysis/REPORT.md"],
]
TYPEA_CASES = [
    ["Bending angle", "theta", "deg", "0 to 90 (A3, A8), 0 to 105 (A6)", "", 0, 105, "5", "", "index PIP", "range target 90 deg; strain limit 20 %", "scripts/a*_parameter_sweep.py"],
    ["Return check: finger weight at 0-10 deg", "M_ret", "N.mm", "return margin >= 1", "", "", "", "", "", "", "the spring must straighten the finger by itself", "docs/report/narrative.py"],
]
MATERIAL = [
    ["TPU modulus (measured, edge tension)", "E", "MPa", "21.0 +/- 2.9 (18.1-23.9)", "21.0", 18.1, 23.9, "value set: 18.1, 21.0, 23.9", "", "", "sensitivity: results scale with E", "results/material_tests/ansys/summary.csv"],
    ["Neo-Hookean mu / D1", "mu, D1", "MPa, 1/MPa", "6.987 / 0.00573 (nu 0.49)", "", "", "", "fixed", "", "", "or D1 = 0 with mixed u-P elements", "scripts/export_ansys_csv.py"],
    ["Strain limit (pass/fail)", "eps_max", "-", "20 % engineering (placeholder until fatigue data)", "20 %", 0.15, 0.25, "0.05", "", "", "from the fatigue test once run", "docs/report"],
]


def P(name, sym, unit, swept, sel, lo, hi, step, fixed, scale, why, src):
    return [name, sym, unit, swept, sel, lo, hi, step, fixed, scale, why, src]


DESIGNS = {
    "B5 crossed strip": dict(
        what="Two pairs of strips crossing at an angle; the joint turns about the crossing. Printed: A (t2.0 deep), B (t1.5 as built), H module (t1.5 deep).",
        params=[
            P("Strip thickness", "t", "mm", "1.00, 1.25, 1.50, 2.00", "1.5 (B, H), 2.0 (A)", 1.0, 2.25, 0.25, "no", GRADE,
              "thinner buckles at lower tendon load; t about 2.0 reaches 20 % near 60 deg", FAM),
            P("Crossing angle", "alpha", "deg", "45, 60, 75", "45", 40, 75, 5, "no", "same at every joint", "45 won; 75 is the last that builds at t >= 2.0", FAM),
            P("Strip width", "w", "mm", "PIP 1.95; MCP 2.45 (2.42 at 75); DIP 1.45/1.405/1.295 (45/60/75)", "1.95", 0.9, 1.95, 0.15, "max is",
              "room left per joint: PIP 1.95, MCP 2.45, DIP 1.45", "1.95 = all the room at the PIP", FAM),
            P("Flex-zone length", "F", "mm", "PIP 7.55, MCP 10.25, DIP 7.30", "7.55", 7.55, 7.55, "fixed", "yes", "per joint as listed", "set by the phalanges", "TYPE B/build_finger_type_b.py"),
            P("Strip length", "Ls", "mm", "F / cos(alpha/2): PIP 8.172 / 8.718 / 9.517 (45/60/75)", "8.172", "", "", "derived", "", "derived", "follows F and alpha", FAM),
            P("Tendon offset (lever)", "y_t", "mm", "as built 1.93 (PIP), deep 3.40 (PIP); MCP 3.06/4.40, DIP 1.06/2.30", "3.40 deep", 1.93, 3.40,
              "value set: 1.93, 3.40", "max is", "per joint as listed", "deep = as far palmar as the section allows", R2),
        ]),
    "B5i inset (K)": dict(
        what="B5 with its collars narrowed to 9.2 mm so PLA hinge plates fit inside the finger's width (design K, pinned).",
        params=[
            P("Strip thickness", "t", "mm", "1.50, 1.75, 2.00, 2.25", "1.75", 1.5, 2.5, 0.25, "no", GRADE, "0.9 mm wide strips buckle sideways without the pin", FAM),
            P("Strip width", "w", "mm", "0.90 at every joint", "0.90", 0.9, 1.2, 0.1, "max is", "same", "set by the narrowed collar", FAM),
            P("Collar half-width", "c_half", "mm", "4.6", "4.6", 4.6, 5.5, 0.3, "no", "PIP only", "wider leaves less room for the hinge plates", FAM),
            P("Crossing angle", "alpha", "deg", "45", "45", 40, 60, 5, "no", "", "", FAM),
            P("Pin offset palmar of the crossing", "dy", "mm", "-0.8", "-0.8", -1.4, 0.0, 0.2, "no", "PIP only", "pinned FEA: follows the free B5's rotation pole", "TYPE B/round2/b5_pinned.py"),
            P("Hinge plate thickness (K2 inner / K1 outer)", "t_pl", "mm", "1.0 / 1.0", "1.0", 1.0, 1.6, 0.2, "no", "", "K2 plate broke at its jogged root: check root bending", "TYPE B/round2/b5_pinned.py"),
            P("Hinge plate gap", "g_pl", "mm", "0.15", "0.15", 0.15, 0.3, 0.05, "no", "", "plates must not print fused", "TYPE B/round2/b5_pinned.py"),
            P("Plate disc radius round the pin", "r_pl", "mm", "3.0", "3.0", 3.0, 4.0, 0.25, "no", "", "", "TYPE B/round2/b5_pinned.py"),
        ]),
    "Pinned B5 (H)": dict(
        what="Unchanged B5 t1.5 deep module between PLA phalanges with hinge plates outside (18.1 mm wide); the pin carries the tendon squeeze.",
        params=[
            P("Module strip thickness", "t", "mm", "1.5 (B5 values 1.0-2.0)", "1.5", 1.0, 2.0, 0.25, "no", GRADE, "the pin carries the squeeze, so thinner is possible", FAM),
            P("Pin diameter", "d_pin", "mm", "2.0 (hole 2.05)", "2.0", 2.0, 3.0, 0.5, "no", "", "printed pins: 1.90 fitted", "TYPE B/round2/b5_pinned.py"),
            P("Pin offset palmar of the crossing", "dy", "mm", "-0.65", "-0.65", -1.2, 0.0, 0.2, "no", "", "pinned FEA (results/PIP_pinned)", "TYPE B/round2/b5_pinned.py"),
            P("Hinge plate thickness", "t_pl", "mm", "1.0 nominal (1.2 as built)", "1.2", 1.0, 1.6, 0.2, "no", "", "", "TYPE B/round2/b5_pinned.py"),
            P("Plate gap", "g_pl", "mm", "0.15 (0.2 as built)", "0.2", 0.15, 0.3, 0.05, "no", "", "", "TYPE B/round2/b5_pinned.py"),
            P("Plate disc radius", "r_pl", "mm", "4.0", "4.0", 3.5, 5.0, 0.5, "no", "", "", "TYPE B/round2/b5_pinned.py"),
        ]),
    "B4 rolling contact": dict(
        what="Two convex lobes that roll on each other, held by crossed straps (design C). Best under tendon load on the rig.",
        params=[
            P("Strap thickness", "t", "mm", "0.8, 1.0", "1.0", 0.6, 1.2, 0.1, "no", GRADE, "straps only locate; the lobes carry the load", R2),
            P("Strap crossing angle", "alpha", "deg", "60", "60", 45, 75, 15, "no", "", "", R2),
            P("Rolling radius", "R", "mm", "derived: (tendon offset - 0.3) / sin(target/2), capped at the half-height", "", "", "", "derived", "", "per joint", "keeps the tendon lever >= 0.3 mm at full flexion", R2),
            P("Bearing gap (as printed)", "gap", "mm", "0.3 (FEA), 0.5 (print version)", "0.5", 0.3, 0.6, 0.1, "no", "", "0.5 stops strings bridging; larger = more slack", R2 + " (GAP), round2/print_gap05"),
            P("Lever margin at full flexion", "m", "mm", "0.3", "0.3", 0.2, 0.5, 0.1, "no", "", "", R2 + " (LEVER_MARGIN)"),
            P("Tendon offset", "y_t", "mm", "deep 3.40 (PIP)", "3.40", 1.93, 3.40, "value set: 1.93, 3.40", "max is", "per joint", "", R2),
        ]),
    "B8 knuckle-in-cup": dict(
        what="A cylindrical knuckle seated in a cup takes the tendon load; thin leaves return the joint (designs E, F).",
        params=[
            P("Knuckle radius", "r", "mm", "1.25, 1.50 (PIP)", "1.25 (E), 1.5 (F)", 1.0, 2.0, 0.25, "no", "scaled with the section", "cup must fit: |y| + r + 0.3 + 0.8 <= half-height", R2),
            P("Knuckle offset dorsal of the axis", "y_pad", "mm", "0.0, 2.0", "2.0 (E), 0.0 (F)", 0.0, 2.5, 0.5, "no", "scaled with the section", "dorsal offset moves the pivot away from the tendon", R2),
            P("Return leaf thickness", "t_leaf", "mm", "0.75 (PIP)", "0.75", 0.6, 1.2, 0.15, "no", GRADE, "0.75 is under two lines: measure the print", R2 + " (LEAF_T)"),
            P("Bearing gap", "gap", "mm", "0.3 (FEA), 0.5 (print version)", "0.5", 0.3, 0.6, 0.1, "no", "", "", R2),
            P("Cup lip (wrap)", "lip", "-", "0.35 (about 139 deg of wrap)", "0.35", 0.25, 0.5, 0.05, "no", "", "more wrap holds sideways better but limits range", R2 + " (SEAT_LIP)"),
            P("Cup wall", "wall", "mm", "0.8", "0.8", 0.8, 1.2, 0.2, "no", "", "", R2 + " (SEAT_WALL)"),
        ]),
    "B3 dual leaf": dict(
        what="One flat leaf each side (design G, control).",
        params=[
            P("Leaf thickness", "t", "mm", "1.00, 1.25, 1.50, 2.00", "1.5", 1.0, 2.25, 0.25, "no", GRADE, "buckles sideways at about 17 N (t2.0)", FAM),
            P("Leaf width", "w", "mm", "2.0, 3.0", "3.0", 1.5, 3.5, 0.5, "max is", "same", "room in the section", FAM),
            P("Taper (root / middle thickness)", "k", "-", "1.0, 1.5, 2.0", "", 1.0, 2.0, 0.25, "no", "", "a thicker root spreads the strain", FAM),
            P("Flex-zone length", "F", "mm", "PIP 7.55, MCP 10.25, DIP 7.30", "7.55", 7.55, 7.55, "fixed", "yes", "per joint", "", "TYPE B/build_finger_type_b.py"),
        ]),
    "B6 multi-leaf": dict(
        what="Several thin leaves sharing 2.0 mm of width per side.",
        params=[
            P("Number of leaves (total)", "n", "-", "4, 6", "4", 2, 8, "value set: 2, 4, 6, 8", "no", "", "more leaves = thinner each, lower strain", FAM),
            P("Leaf thickness", "t", "mm", "1.00, 1.25, 1.50, 2.00", "1.5", 0.6, 1.5, 0.15, "no", GRADE, "", FAM),
            P("Leaf width", "w", "mm", "1.000 (4 leaves), 0.667 (6 leaves)", "1.0", "", "", "derived: 2.0 / (n/2)", "", "", "0.6 mm = printing minimum", FAM),
            P("Taper", "k", "-", "1.0, 1.5, 2.0", "1.5", 1.0, 2.0, 0.25, "no", "", "", FAM),
        ]),
    "B1 hourglass": dict(
        what="A single web with a curved notch each side (throat in the middle).",
        params=[
            P("Throat thickness", "t", "mm", "1.00, 1.25, 1.50, 2.00", "1.0", 0.8, 2.0, 0.2, "no", GRADE, "reached 20 % at 46 deg (t1.0, full notch)", FAM),
            P("Notch length (fraction of the flex zone)", "f", "-", "0.5, 1.0", "1.0", 0.25, 1.0, 0.25, "no", "", "longer notch = longer bending length = lower strain", FAM),
            P("Web width", "w", "mm", "3.0", "3.0", 2.0, 4.0, 0.5, "max is", "", "", FAM),
            P("Web height", "h", "mm", "PIP 8.907, MCP 10.907, DIP 6.907", "", "", "", "derived", "", "per joint", "", FAM),
        ]),
    "B-lattice": dict(
        what="Bow-tie lattice of struts (the original Type B).",
        params=[
            P("Strut thickness scale", "T", "-", "0.9, 1.0, 1.1", "0.9", 0.8, 1.3, 0.1, "no", "", "struts buckle near 10 deg", "TYPE B/B_lattice/"),
            P("Number of cells", "X", "-", "2, 3, 4 (+ baseline)", "3", 2, 5, 1, "no", "", "", "TYPE B/B_lattice/"),
        ]),
    "A3 strap": dict(
        what="Curved TPU strap beside the pinned PIP (Type A).",
        params=[
            P("Strap thickness", "t", "mm", "0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6", "1.0 (as built)", 0.4, 1.6, 0.1, "no", "", "strain ~ t; torque ~ t^3", "scripts/a3_parameter_sweep.py"),
            P("Strap width", "w", "mm", "1.5, 2.0, 2.5, 3.0, 3.5, 4.0 (cap 4.2)", "2.0", 1.5, 4.2, 0.3, "max is", "", "pitch 5.7 mm minus a 1.5 mm gap", "scripts/a3_parameter_sweep.py"),
            P("Arch radius", "R", "mm", "16, 20, 25, 30, 35, 41.4, 50, 60, 80, 120 (iteration 3: 14-120)", "41.4 (as built)", 14, 120,
              "value set: 14, 16, 20, 25, 30, 41.4, 50, 80, 120", "no", "", "flatter = stiffer at the start", "scripts/a3_parameter_sweep.py, scripts/iteration3_a3.py"),
        ]),
    "A6 sliding leaf": dict(
        what="Curved leaf that slides in a guide on the middle phalanx (Type A).",
        params=[
            P("Leaf radius", "R", "mm", "22, 24, 26, 28, 30, 32, 35, 40 (iteration 3: 18, 22, 26, 30, 35, 45, 60, flat)", "45 / 60 (it3)", 18, 60,
              "value set: 18, 22, 26, 30, 35, 45, 60", "no", "", "", "scripts/a6_parameter_sweep.py, scripts/iteration3_a6.py"),
            P("Leaf thickness", "t", "mm", "0.6-2.0 step 0.2 (+ 2.4, 2.8, 3.2 at R 35-60)", "3.2 (it3)", 0.6, 3.2, 0.2, "no", "", "strain ~ t", "scripts/iteration3_a6.py"),
            P("Leaf width", "w", "mm", "4, 5, 6", "6", 4.0, 6.0, 1.0, "max is", "", "must fit the guide in the cuff", "scripts/iteration3_a6.py"),
            P("Travel", "s", "mm", "9.5-14.5 step 0.5 (it3: 8-20 step 0.5)", "19", 8.0, 20.0, 0.5, "no", "", "travel window must stay inside the guide", "scripts/a6_rom_check.py, scripts/iteration3_a6.py"),
        ]),
    "A8 meander": dict(
        what="Serpentine strip spanning the PIP (Type A).",
        params=[
            P("Number of turns", "n", "-", "2, 3, 4", "2", 2, 4, 1, "no", "", "2 won", "scripts/a8_meander_study.py"),
            P("True width (across the strip)", "w", "mm", "1.2 (printable minimum: 2 lines)", "1.2", 1.2, 1.6, 0.2, "min is", "", "0.4 mm nozzle", "scripts/a8_meander_study.py"),
            P("Height", "h", "mm", "1.2, 1.8, 2.4 (it3 1.5, 1.8, 2.4)", "1.8", 1.2, 2.4, 0.3, "no", "", "", "scripts/a8_meander_study.py, scripts/iteration3_a8.py"),
            P("Spine sagitta", "s", "mm", "0, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5 (printable 2.5, 3.0, 3.5, 4.5)", "0.75", 0.0, 3.5, 0.25, "no", "", "", "scripts/a8_meander_study.py"),
            P("Lobe amplitude", "a", "mm", "5.5 (2 turns), 3.5 (3 turns)", "5.5", 4.5, 6.0, 0.5, "no", "", "must clear the bones and the MC2 socket", "scripts/iteration3_a8.py"),
        ]),
}


def write_rows(ws, r, rows, fill=None):
    for row in rows:
        for j, v in enumerate(row):
            c = ws.cell(r, j + 1, v)
            c.border = BOX
            c.alignment = WRAP
            if fill:
                c.fill = fill
        r += 1
    return r


def header(ws, r):
    for j, h in enumerate(COLS):
        c = ws.cell(r, j + 1, h)
        c.font = Font(bold=True)
        c.fill = HEAD
        c.border = BOX
        c.alignment = WRAP
    return r + 1


def main():
    wb = Workbook()
    ov = wb.active
    ov.title = "Overview"
    ov["A1"] = "TPU joint designs: parameter ranges to test"
    ov["A1"].font = Font(bold=True, size=13)
    ov["A2"] = ("One sheet per design. 'Swept in the project' = exact values from the build scripts (Source column). "
                "'Suggested' = a range for new runs, with the reason; green = the printed/selected value; grey = fixed by the finger. "
                "Thickness is set at the PIP; MCP = PIP x 1.2727, DIP = PIP x 0.8182. Each sheet ends with the bending angles and loads to run.")
    ov["A2"].alignment = WRAP
    ov.merge_cells("A2:F2")
    ov.row_dimensions[2].height = 60
    for j, h in enumerate(["Sheet", "Design", "Type", "Printed variants", "Parameters"]):
        c = ov.cell(4, j + 1, h); c.font = Font(bold=True); c.fill = HEAD; c.border = BOX
    r = 5
    for name, d in DESIGNS.items():
        kind = "A (spring beside a pin)" if name.startswith("A") else "B (TPU joint)"
        for j, v in enumerate([name, d["what"], kind, ", ".join(str(p[4]) for p in d["params"] if p[4]),
                               len(d["params"])]):
            c = ov.cell(r, j + 1, v); c.border = BOX; c.alignment = WRAP
        r += 1
    r += 1
    ov.cell(r, 1, "Fixed by the finger").font = Font(bold=True)
    r += 1
    r = write_rows(ov, r, [["", "MCP", "PIP", "DIP"], ["Module section (w x h, mm)", "16 x 14", "14 x 12", "12 x 10"],
                           ["Flex-zone length (mm)", 10.25, 7.55, 7.30], ["Thickness grade", 1.2727, 1.0, 0.8182],
                           ["Target flexion (deg)", 90, 100, 80], ["Tendon offset as built / deep (mm)", "3.06 / 4.40", "1.93 / 3.40", "1.06 / 2.30"]])
    for col, w in zip("ABCDEF", (24, 70, 18, 34, 10, 10)):
        ov.column_dimensions[col].width = w

    for name, d in DESIGNS.items():
        ws = wb.create_sheet(name[:31])
        ws["A1"] = name
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = d["what"]
        ws["A2"].alignment = WRAP
        ws.merge_cells("A2:L2")
        ws.row_dimensions[2].height = 30
        r = header(ws, 4)
        for p in d["params"]:
            fill = FIX if p[8] == "yes" else None
            r = write_rows(ws, r, [p], fill)
            if p[4]:
                ws.cell(r - 1, 5).fill = SEL
        r += 1
        ws.cell(r, 1, "Bending angles and loads to run").font = Font(bold=True)
        ws.cell(r, 1).fill = SEC
        r = header(ws, r + 1)
        r = write_rows(ws, r, TYPEA_CASES if name.startswith("A") else TYPEB_CASES)
        r += 1
        ws.cell(r, 1, "Material and pass/fail").font = Font(bold=True)
        ws.cell(r, 1).fill = SEC
        r = header(ws, r + 1)
        r = write_rows(ws, r, MATERIAL)
        r += 1
        ws.cell(r, 1, "Outputs per run: reaction moment vs angle; peak max/min principal strain vs angle (engineering, "
                      "ignoring 0.4 mm at sharp roots); reaction force; contact status; twist under side load.")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=12)
        ws.cell(r, 1).alignment = WRAP
        ws.row_dimensions[r].height = 30
        for j, w in enumerate(WIDTHS):
            ws.column_dimensions[chr(65 + j)].width = w
        ws.freeze_panes = "B5"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT, "sheets:", wb.sheetnames)


if __name__ == "__main__":
    main()
