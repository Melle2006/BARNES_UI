"""Workbook for test C (compression) of docs/12-tpu-specimen-test-procedure.md.

    python3 scripts/make_compression_workbook.py

Writes results/material_tests/compression_test_C.xlsx: one sheet per cylinder (C1-C3), each
with run 1 and run 2 (run 2 is the one used), and a Summary sheet. Blue cells are for you to
fill in; black cells are worked out.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parents[1] / "results" / "material_tests" / "compression_test_C.xlsx"
STEPS_MM = [round(0.2 * k, 1) for k in range(0, 8)]       # 0 to 1.4 mm; stop at about 1.0 mm

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


def run_block(ws, top, label):
    """One run: h0, then the readings. Returns the result cell refs."""
    cell(ws, f"A{top}", label, bold=True, fill=HEAD_FILL)
    cell(ws, f"A{top + 1}", "Calipers across both plates, press just touching, scale ≈ 0 (mm)", bold=True)
    cell(ws, f"E{top + 1}", None, inp=True, fmt="0.00")
    cell(ws, f"A{top + 2}", "h₀ = that − both plate thicknesses (mm)", bold=True)
    cell(ws, f"E{top + 2}", f'=IF(OR(E{top + 1}="",$E$11=""),"",E{top + 1}-$E$11)', fmt="0.000", fill=RES_FILL)
    h0 = f"$E${top + 2}"
    r0 = top + 4
    heads = ["Reading", "Press about (mm)", "Calipers across plates (mm)", "Height h (mm)", "Scale (kg)",
             "Force F (N)", "Strain ε", "Stress σ (MPa)", "E for the row (MPa)", "In 2–10 % window?", "Notes"]
    for i, h in enumerate(heads):
        c = cell(ws, f"{get_column_letter(1 + i)}{r0}", h, bold=True, fill=HEAD_FILL)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[r0].height = 32
    rows = []
    for k, mm in enumerate(STEPS_MM):
        r = r0 + 1 + k
        rows.append(r)
        cell(ws, f"A{r}", k)
        cell(ws, f"B{r}", mm, fmt="0.0")
        cell(ws, f"C{r}", None, inp=True, fmt="0.00")
        cell(ws, f"D{r}", f'=IF(OR(C{r}="",$E$11=""),"",C{r}-$E$11)', fmt="0.000")
        cell(ws, f"E{r}", None, inp=True, fmt="0.000")
        cell(ws, f"F{r}", f'=IF(E{r}="","",E{r}*9.81)', fmt="0.00")
        cell(ws, f"G{r}", f'=IF(OR(D{r}="",{h0}=""),"",({h0}-D{r})/{h0})', fmt="0.0000")
        cell(ws, f"H{r}", f'=IF(OR(F{r}="",$E$8=""),"",F{r}/$E$8)', fmt="0.000")
        cell(ws, f"I{r}", f'=IF(OR(G{r}="",H{r}="",G{r}<=0),"",3*H{r}/(1/(1-G{r})^2-(1-G{r})))', fmt="0.00")
        cell(ws, f"J{r}", f'=IF(G{r}="","",IF(AND(G{r}>=0.02,G{r}<=0.1),"yes",""))')
        cell(ws, f"K{r}", None, inp=True)
    a, b = rows[0], rows[-1]
    rr = b + 1
    cell(ws, f"A{rr}", "Readings in the 2–10 % window (need at least 4)", bold=True)
    cell(ws, f"E{rr}", f'=COUNTIFS(G{a}:G{b},">=0.02",G{a}:G{b},"<=0.1")', fill=RES_FILL)
    cell(ws, f"A{rr + 1}", "E (MPa) = average of 'E for the row' in the window", bold=True)
    cell(ws, f"E{rr + 1}", f'=IFERROR(AVERAGEIFS(I{a}:I{b},G{a}:G{b},">=0.02",G{a}:G{b},"<=0.1"),"")',
         fmt="0.00", fill=RES_FILL)
    return f"E{rr + 1}", f"E{rr}", rr + 3


def cylinder_sheet(wb, n):
    name = f"C{n}"
    ws = wb.create_sheet(name)
    ws["A1"] = f"{name}: test C, compression, Ø10 × 10 mm cylinder (write {name} on it)"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = ("Blue cells: fill in. Black cells are worked out. The press must push against the bench, so the "
                "force goes through the scale.")
    ws["A2"].font = Font(italic=True, color="666666")
    cell(ws, "A4", "Date", bold=True); cell(ws, "B4", None, inp=True)
    cell(ws, "C4", "Room temperature (°C)", bold=True); cell(ws, "D4", None, inp=True)
    cell(ws, "A6", "Measurement", bold=True, fill=HEAD_FILL)
    for i, h in enumerate(["point 1", "point 2", "point 3", "average"]):
        cell(ws, f"{get_column_letter(2 + i)}6", h, bold=True, fill=HEAD_FILL)
    cell(ws, "A7", "diameter d at 3 heights (mm)", bold=True)
    for col in "BCD":
        cell(ws, f"{col}7", None, inp=True, fmt="0.00")
    cell(ws, "E7", '=IF(COUNT(B7:D7)=3,AVERAGE(B7:D7),"")', fmt="0.000")
    cell(ws, "A8", "area A = π d² ÷ 4 (mm²)", bold=True)
    cell(ws, "E8", '=IF(E7="","",PI()*E7^2/4)', fmt="0.00", fill=RES_FILL)
    cell(ws, "A9", "bottom plate thickness (mm)", bold=True); cell(ws, "E9", None, inp=True, fmt="0.00")
    cell(ws, "A10", "top plate thickness (mm)", bold=True); cell(ws, "E10", None, inp=True, fmt="0.00")
    cell(ws, "A11", "both plates (mm)", bold=True)
    cell(ws, "E11", '=IF(OR(E9="",E10=""),"",E9+E10)', fmt="0.00")
    cell(ws, "A12", "grease / oil on both ends?", bold=True); cell(ws, "E12", None, inp=True)
    e1, n1, nxt = run_block(ws, 14, "RUN 1 (settles the cylinder; not used for E)")
    cell(ws, f"A{nxt - 1}", "Wait 5 minutes, then run 2", bold=True)
    e2, n2, nxt2 = run_block(ws, nxt, "RUN 2 (this is the one used)")
    cell(ws, f"A{nxt2}", "RESULT: E for this cylinder (run 2), MPa", bold=True, fill=RES_FILL)
    cell(ws, f"E{nxt2}", f'=IF({e2}="","",{e2})', fmt="0.00", fill=RES_FILL)
    cell(ws, f"A{nxt2 + 1}", "Run 2 against run 1 (%): a big difference means the first run was still settling", bold=True)
    cell(ws, f"E{nxt2 + 1}", f'=IFERROR(({e2}-{e1})/{e1}*100,"")', fmt="0.0")
    cell(ws, f"A{nxt2 + 2}", "Notes (scale creep, cylinder slid, anything odd)", bold=True)
    cell(ws, f"E{nxt2 + 2}", None, inp=True)
    ws.column_dimensions["A"].width = 62
    for col, w in zip("BCDEFGHIJK", (11, 14, 11, 11, 11, 11, 12, 13, 12, 24)):
        ws.column_dimensions[col].width = w
    return name, f"E{nxt2}", n2


def main():
    wb = Workbook()
    summ = wb.active
    summ.title = "Summary"
    refs = [cylinder_sheet(wb, n) for n in (1, 2, 3)]
    summ["A1"] = "Test C (compression): summary. Fill in each cylinder's sheet; this page fills itself."
    summ["A1"].font = Font(bold=True, size=12)
    for i, h in enumerate(["Cylinder", "Readings in window (run 2)", "E, run 2 (MPa)"]):
        cell(summ, f"{get_column_letter(1 + i)}3", h, bold=True, fill=HEAD_FILL)
    r = 4
    for name, e_ref, n_ref in refs:
        cell(summ, f"A{r}", name)
        cell(summ, f"B{r}", f"='{name}'!{n_ref}")
        cell(summ, f"C{r}", f"=IF('{name}'!{e_ref}=\"\",\"\",'{name}'!{e_ref})", fmt="0.00")
        r += 1
    rng = "C4:C6"
    r += 1
    cell(summ, f"A{r}", "E, compression (mean of C1–C3), MPa", bold=True)
    cell(summ, f"C{r}", f'=IFERROR(AVERAGE({rng}),"")', fmt="0.00", fill=RES_FILL)
    mean = f"C{r}"
    r += 1
    cell(summ, f"A{r}", "All three within ±10 % of the mean?", bold=True)
    cell(summ, f"C{r}", f'=IF({mean}="","",IF(AND(MAX({rng})<=1.1*{mean},MIN({rng})>=0.9*{mean}),"yes",'
                        f'"no: check the odd one"))')
    r += 2
    cell(summ, f"A{r}", "E, tension, printed on edge, from tension_tests_AB.xlsx (copy it here), MPa", bold=True)
    cell(summ, f"C{r}", None, inp=True, fmt="0.00")
    edge = f"C{r}"
    r += 1
    cell(summ, f"A{r}", "Compression against tension (%): within about 20 % is normal", bold=True)
    cell(summ, f"C{r}", f'=IFERROR(({mean}-{edge})/{edge}*100,"")', fmt="0.0")
    summ.column_dimensions["A"].width = 78
    summ.column_dimensions["B"].width = 26
    summ.column_dimensions["C"].width = 16
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
