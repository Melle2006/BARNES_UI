"""Workbook for tests A and B (tension) of docs/12-tpu-specimen-test-procedure.md.

    python3 scripts/make_tension_workbook.py

Writes results/material_tests/tension_tests_AB.xlsx: one sheet per specimen (F1-1..3,
F2-1..3, E1-1..3, E2-1..3) with the planned load steps and every formula in place, and a
Summary sheet. Blue cells are for you to fill in; black cells are worked out.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parents[1] / "results" / "material_tests" / "tension_tests_AB.xlsx"

SPECIMENS = [
    ("F1", "A. tension, dog-bone 1BA 1.0 mm, printed flat", "width", 100, 2000),
    ("F2", "A. tension, dog-bone 1BA 2.0 mm, printed flat", "width", 200, 4000),
    ("E1", "B. tension, strip 1.0 mm, printed on edge", "height", 100, 2000),
    ("E2", "B. tension, strip 2.0 mm, printed on edge", "height", 200, 4000),
]
COND_MASS = {"F1": 0.9, "F2": 1.8, "E1": 1.1, "E2": 2.2}

INPUT = Font(color="0000CC")
BOLD = Font(bold=True)
HEAD_FILL = PatternFill("solid", fgColor="DDE6F0")
IN_FILL = PatternFill("solid", fgColor="FFF8DC")
RES_FILL = PatternFill("solid", fgColor="E2F0D9")
THIN = Side(style="thin", color="BBBBBB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def cell(ws, ref, value, inp=False, bold=False, fmt=None, fill=None):
    c = ws[ref]
    c.value = value
    if inp:
        c.font = INPUT
        c.fill = IN_FILL
    if bold:
        c.font = BOLD
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    c.border = BOX
    return c


def specimen_sheet(wb, code, copy, title, dim_name, step_g, max_g):
    name = f"{code}-{copy}"
    ws = wb.create_sheet(name)
    ws["A1"] = f"{name}: {title}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = "Blue cells: fill in. Black cells are worked out. Strain is a fraction (0.05 = 5 %)."
    ws["A2"].font = Font(italic=True, color="666666")

    # header block
    cell(ws, "A4", "Date", bold=True); cell(ws, "B4", None, inp=True)
    cell(ws, "C4", "Room temperature (°C)", bold=True); cell(ws, "D4", None, inp=True)
    cell(ws, "A6", "Measurement", bold=True, fill=HEAD_FILL)
    for i, h in enumerate(["point 1", "point 2", "point 3", "average"]):
        cell(ws, f"{get_column_letter(2 + i)}6", h, bold=True, fill=HEAD_FILL)
    cell(ws, "A7", f"{dim_name} (mm)", bold=True)
    cell(ws, "A8", "thickness (mm)", bold=True)
    for r in (7, 8):
        for col in "BCD":
            cell(ws, f"{col}{r}", None, inp=True, fmt="0.00")
        cell(ws, f"E{r}", f'=IF(COUNT(B{r}:D{r})=3,AVERAGE(B{r}:D{r}),"")', fmt="0.000")
    cell(ws, "A9", "area A (mm²)", bold=True)
    cell(ws, "E9", '=IF(AND(E7<>"",E8<>""),E7*E8,"")', fmt="0.000", fill=RES_FILL)

    cell(ws, "A11", "Conditioning (step 2)", bold=True, fill=HEAD_FILL)
    cell(ws, "B11", "mass used (kg)", bold=True, fill=HEAD_FILL)
    cell(ws, "C11", "done ✓", bold=True, fill=HEAD_FILL)
    for k in range(3):
        cell(ws, f"A{12 + k}", f"cycle {k + 1} (load, wait 30 s, unload)")
        cell(ws, f"B{12 + k}", COND_MASS[code], inp=True, fmt="0.00")
        cell(ws, f"C{12 + k}", None, inp=True)
    cell(ws, "A16", "L₀ (mm), empty bag only, 2 min after conditioning (step 3)", bold=True)
    cell(ws, "E16", None, inp=True, fmt="0.00")

    # readings
    r0 = 18
    heads = ["Reading", "Added mass (g)", "Force F (N)", "Mark gap L (mm)", "Strain ε", "Stress σ (MPa)",
             "E for the row (MPa)", "In 2–10 % window?", "Photo / notes"]
    for i, h in enumerate(heads):
        c = cell(ws, f"{get_column_letter(1 + i)}{r0}", h, bold=True, fill=HEAD_FILL)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    masses = list(range(0, max_g + 1, step_g))
    rows = []
    for k, m in enumerate(masses):
        r = r0 + 1 + k
        rows.append(r)
        cell(ws, f"A{r}", k)
        cell(ws, f"B{r}", m, inp=True, fmt="0")
        cell(ws, f"C{r}", f'=IF(B{r}="","",B{r}/1000*9.81)', fmt="0.000")
        cell(ws, f"D{r}", None, inp=True, fmt="0.00")
        cell(ws, f"E{r}", f'=IF(OR(D{r}="",$E$16=""),"",(D{r}-$E$16)/$E$16)', fmt="0.0000")
        cell(ws, f"F{r}", f'=IF(OR(C{r}="",$E$9=""),"",C{r}/$E$9)', fmt="0.000")
        cell(ws, f"G{r}", f'=IF(OR(E{r}="",F{r}="",E{r}<=0),"",3*F{r}/((1+E{r})-1/(1+E{r})^2))', fmt="0.00")
        cell(ws, f"H{r}", f'=IF(E{r}="","",IF(AND(E{r}>=0.02,E{r}<=0.1),"yes",""))')
        cell(ws, f"I{r}", None, inp=True)
    a, b = rows[0], rows[-1]
    rr = b + 2
    cell(ws, f"A{rr}", "RESULT", bold=True, fill=RES_FILL)
    cell(ws, f"A{rr + 1}", "Readings in the 2–10 % window (need at least 4)", bold=True)
    cell(ws, f"E{rr + 1}", f'=COUNTIFS(E{a}:E{b},">=0.02",E{a}:E{b},"<=0.1")', fill=RES_FILL)
    cell(ws, f"A{rr + 2}", "E (MPa) = average of 'E for the row' in the window", bold=True)
    cell(ws, f"E{rr + 2}", f'=IFERROR(AVERAGEIFS(G{a}:G{b},E{a}:E{b},">=0.02",E{a}:E{b},"<=0.1"),"")',
         fmt="0.00", fill=RES_FILL)
    cell(ws, f"A{rr + 3}", "Spread of 'E for the row' in the window, max − min (MPa)", bold=True)
    cell(ws, f"E{rr + 3}", f'=IFERROR(_xlfn.MAXIFS(G{a}:G{b},E{a}:E{b},">=0.02",E{a}:E{b},"<=0.1")'
                           f'-_xlfn.MINIFS(G{a}:G{b},E{a}:E{b},">=0.02",E{a}:E{b},"<=0.1"),"")', fmt="0.00")
    cell(ws, f"A{rr + 4}", "Stress at 20 % strain if reached (MPa): read from the table", bold=True)
    cell(ws, f"E{rr + 4}", None, inp=True, fmt="0.00")
    cell(ws, f"A{rr + 5}", "Notes (slipped grip, voids, anything odd)", bold=True)
    cell(ws, f"E{rr + 5}", None, inp=True)
    ws.column_dimensions["A"].width = 52
    for col, w in zip("BCDEFGHI", (14, 12, 14, 12, 13, 15, 14, 26)):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[r0].height = 32
    ws.freeze_panes = f"A{r0 + 1}"
    return name, f"E{rr + 2}", f"E{rr + 1}"


def main():
    wb = Workbook()
    summ = wb.active
    summ.title = "Summary"
    refs = {}
    for code, title, dim, step, mx in SPECIMENS:
        for cp in (1, 2, 3):
            refs[(code, cp)] = specimen_sheet(wb, code, cp, title, dim, step, mx)

    summ["A1"] = "Tests A and B (tension): summary. Fill in each specimen's sheet; this page fills itself."
    summ["A1"].font = Font(bold=True, size=12)
    heads = ["Specimen", "Test", "Readings in window", "E (MPa)"]
    for i, h in enumerate(heads):
        cell(summ, f"{get_column_letter(1 + i)}3", h, bold=True, fill=HEAD_FILL)
    r = 4
    group_rows = {}
    for code, title, *_ in SPECIMENS:
        group_rows[code] = []
        for cp in (1, 2, 3):
            name, e_ref, n_ref = refs[(code, cp)]
            cell(summ, f"A{r}", name)
            cell(summ, f"B{r}", title)
            cell(summ, f"C{r}", f"='{name}'!{n_ref}")
            cell(summ, f"D{r}", f"=IF('{name}'!{e_ref}=\"\",\"\",'{name}'!{e_ref})", fmt="0.00")
            group_rows[code].append(r)
            r += 1
    r += 1
    cell(summ, f"A{r}", "Group", bold=True, fill=HEAD_FILL)
    cell(summ, f"B{r}", "Mean E (MPa)", bold=True, fill=HEAD_FILL)
    cell(summ, f"C{r}", "Copies within ±10 % of the mean?", bold=True, fill=HEAD_FILL)
    r += 1
    mean_ref = {}
    for code, title, *_ in SPECIMENS:
        rows = group_rows[code]
        rng = f"D{rows[0]}:D{rows[-1]}"
        cell(summ, f"A{r}", code)
        cell(summ, f"B{r}", f'=IFERROR(AVERAGE({rng}),"")', fmt="0.00", fill=RES_FILL)
        cell(summ, f"C{r}", f'=IF(B{r}="","",IF(AND(MAX({rng})<=1.1*B{r},MIN({rng})>=0.9*B{r}),"yes",'
                            f'"no: check the odd one"))')
        mean_ref[code] = f"B{r}"
        r += 1
    r += 1
    rows_out = [
        ("E, tension, printed flat (mean of F1 and F2), MPa", f'=IFERROR(AVERAGE({mean_ref["F1"]},{mean_ref["F2"]}),"")'),
        ("E, tension, printed on edge (mean of E1 and E2), MPa  ← the main number",
         f'=IFERROR(AVERAGE({mean_ref["E1"]},{mean_ref["E2"]}),"")'),
    ]
    first = r
    for label, f in rows_out:
        cell(summ, f"A{r}", label, bold=True)
        cell(summ, f"D{r}", f, fmt="0.00", fill=RES_FILL)
        r += 1
    cell(summ, f"A{r}", "Edge against flat, difference (%): over 15 % means print direction matters", bold=True)
    cell(summ, f"D{r}", f'=IFERROR((D{first + 1}-D{first})/D{first}*100,"")', fmt="0.0")
    r += 1
    cell(summ, f"A{r}", "Rescale factor for the analyses = E (edge) ÷ 12 MPa", bold=True)
    cell(summ, f"D{r}", f'=IFERROR(D{first + 1}/12,"")', fmt="0.000", fill=RES_FILL)
    summ.column_dimensions["A"].width = 70
    summ.column_dimensions["B"].width = 46
    summ.column_dimensions["C"].width = 30
    summ.column_dimensions["D"].width = 12
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
