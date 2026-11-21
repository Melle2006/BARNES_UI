"""Workbook for the Type B bending-rig tests (docs/12-tpu-specimen-test-procedure.md, Part 2).

    python3 scripts/make_rig_workbook.py

Writes results/rig_tests/rig_tests_typeB.xlsx: a read-me (what to test, in what order), a
Setup sheet (pulley friction, hanger masses: used by every sheet), one sheet per module copy
with the five rig steps and that module's predictions at the measured E = 21.0 MPa, and a
Summary sheet with the pass criteria. Blue cells are for you to fill in.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

OUT = Path(__file__).resolve().parents[1] / "results" / "rig_tests" / "rig_tests_typeB.xlsx"

INPUT = Font(color="0000CC")
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="DDE6F0")
IN = PatternFill("solid", fgColor="FFF8DC")
RES = PatternFill("solid", fgColor="E2F0D9")
THIN = Side(style="thin", color="BBBBBB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="center")

#: label, design, phalanges, copy role, priority, predicted tendon pull to 30 deg (N, 21 MPa),
#: predicted way of giving way at 30 deg, tendon lever (mm)
MODULES = [
    ("H1-P", "Pinned B5, plates outside (B5 t1.5 deep)", "H1, H2 + 2 hinge pins Ø2", "copy 1: steps 1, 2, 3, 4", 1,
     1.00, "no buckle up to the 47 N stop (the pins carry it)", 2.75),
    ("H2-P", "Pinned B5, plates outside (B5 t1.5 deep)", "H1, H2 + 2 hinge pins Ø2", "copy 2: steps 1, 2, 4, 5", 1,
     1.00, "(step 3 not done on copy 2)", 2.75),
    ("K1-P", "Inset pinned B5 (strips t1.75)", "K1, K2 + 2 hinge pins Ø2 × 1.8", "copy 1: steps 1, 2, 3, 4", 1,
     0.86, "no buckle up to the 47 N stop (the pins carry it)", 2.60),
    ("K2-P", "Inset pinned B5 (strips t1.75)", "K1, K2 + 2 hinge pins Ø2 × 1.8", "copy 2: steps 1, 2, 4, 5", 1,
     0.86, "(step 3 not done on copy 2)", 2.60),
    ("A1-P", "B5 crossed strip t2.0, deep tendon", "X1, X2", "copy 1: steps 1, 2, 3, 4", 2,
     2.31, "20 % strain / bowing between 53 N (0°) and 18 N (60°); likely reaches the 47 N stop at 30°", 3.40),
    ("A2-P", "B5 crossed strip t2.0, deep tendon", "X1, X2", "copy 2: steps 1, 2, 4, 5", 2,
     2.31, "(step 3 not done on copy 2)", 3.40),
    ("B1-P", "B5 crossed strip t1.5, as built", "S1, S2", "copy 1: steps 1, 2, 3, 4", 3,
     1.68, "buckles between 29 N (0°) and 11 N (60°)", 1.93),
    ("B2-P", "B5 crossed strip t1.5, as built", "S1, S2", "copy 2: steps 1, 2, 4, 5", 3,
     1.68, "(step 3 not done on copy 2)", 1.93),
    ("C-P", "B4 rolling contact t1.0, deep (0.5 mm gap)", "X1, X2", "single copy: steps 1, 2, 4, then 3", 4,
     0.35, "at least 19 N at 0° (26 N on the compression modulus); lever falls as it rolls", 2.35),
    ("E-P", "B8 knuckle 2 mm dorsal, r1.25, deep (0.5 mm gap)", "X1, X2", "single copy: steps 1, 2, 4, then 3", 4,
     0.04, "at least 8.6 N at 0° (12 N on the compression modulus); may snap sideways before seating", 6.19),
    ("F-P", "B8 knuckle central, r1.5, as built (0.5 mm gap)", "S1, S2", "single copy: steps 1, 2, 4, then 3", 4,
     0.07, "at least 10 N at 0° (14 N on the compression modulus); may snap sideways before seating", 2.84),
    ("G-P", "B3 dual leaf t1.5, as built (optional control)", "S1, S2", "single copy: steps 1, 2, 4, then 3", 5,
     1.40, "buckles sideways, below B3 t2.0's 17 N", 1.93),
]
MODES = "buckle,squash,twist,crack,line cut,none at 47 N"


def c(ws, ref, v=None, inp=False, bold=False, fmt=None, fill=None, wrap=False):
    x = ws[ref]
    x.value = v
    if inp:
        x.font, x.fill = INPUT, IN
    if bold:
        x.font = BOLD
    if fmt:
        x.number_format = fmt
    if fill:
        x.fill = fill
    if wrap:
        x.alignment = WRAP
    x.border = BOX
    return x


def head(ws, row, labels, height=32):
    for i, h in enumerate(labels):
        c(ws, f"{chr(65 + i)}{row}", h, bold=True, fill=HEAD, wrap=True)
    ws.row_dimensions[row].height = height


def readme(wb):
    ws = wb.active
    ws.title = "Read me"
    ws["A1"] = "Type B bending-rig tests: what to test, in what order"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = ("Procedure: docs/12-tpu-specimen-test-procedure.md, Part 2 (sections 6-10). Fill the Setup sheet first; "
                "then one sheet per module copy. Blue cells are inputs. Predictions are at the measured E = 21.0 MPa.")
    ws["A2"].alignment = WRAP
    ws.row_dimensions[2].height = 30
    head(ws, 4, ["Priority", "Module", "Design", "Phalanges + pins", "Which steps", "Why test it"])
    why = {1: "the pinned hybrids: the designs Type B is betting on; check pin rub, the offset pivot, no buckling",
           2: "the best free Type B joint; straight it now reaches the servo's limit",
           3: "round-1 winner, as built: the reference for what the deep tendon and the pin add",
           4: "the bearings: only a print shows whether they seat (their FEA stopped at lower bounds)",
           5: "optional plain-leaf control"}
    for i, m in enumerate(MODULES):
        r = 5 + i
        for col, v in zip("ABCDEF", (m[4], m[0], m[1], m[2], m[3], why[m[4]])):
            c(ws, f"{col}{r}", v, wrap=True)
    r = 5 + len(MODULES) + 1
    notes = [
        "Rig parts: RIG base, ADP load adapter, PUL pulley (623ZZ bearing, M3 bolt); 8 tab pins Ø2 per assembly "
        "(about 14 mm × 2, 12 mm × 4, 10-11 mm × 2); braided line 0.5-0.8 mm; two light hangers; weights to 5 kg; rest block; stop.",
        "One set of phalanges serves every module of its kind: pull the pins and swap the module. Phalanx 3 is not used.",
        "Order inside each sheet: step 1, 2, (3 on copy 1 / single copies last), 4, (5 on copy 2). Steps 3 and 5 are destructive.",
        "Pass (Summary sheet): holds at least 2 N at the 44.8 mm hole at 30° with T ≤ 47 N; gives way gradually (squash or "
        "none) rather than suddenly; springs back to within 5° after 10 min; survives 1,000 cycles.",
    ]
    for n in notes:
        ws[f"A{r}"] = n
        ws[f"A{r}"].alignment = WRAP
        ws.merge_cells(f"A{r}:F{r}")
        ws.row_dimensions[r].height = 30
        r += 1
    for col, w in zip("ABCDEF", (9, 10, 40, 26, 30, 60)):
        ws.column_dimensions[col].width = w


def setup(wb):
    ws = wb.create_sheet("Setup")
    ws["A1"] = "Setup: once per session (every module sheet uses these)"
    ws["A1"].font = Font(bold=True, size=12)
    rows = [("Date", None, None), ("Room temperature (°C)", None, None),
            ("Pulley friction: equal masses hung on each side (g)", 500, "0"),
            ("Pulley friction: extra on one side to start it moving (g)", None, "0.0"),
            ("Pulley friction (%) = extra ÷ equal × 100", "=IF(OR(B5=\"\",B5=0),0,B6/B5*100)", "0.00"),
            ("Tendon hanger, empty (kg)", None, "0.000"), ("Fingertip hanger, empty (kg)", None, "0.000")]
    for i, (lab, v, fmt) in enumerate(rows):
        r = 3 + i
        c(ws, f"A{r}", lab, bold=True)
        c(ws, f"B{r}", v, inp=not (isinstance(v, str) and v.startswith("=")), fmt=fmt,
          fill=RES if isinstance(v, str) else None)
    ws["A11"] = "Under 2 % friction can be ignored; the sheets reduce every tendon tension by it anyway."
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 14


FRIC, HT, HF = "Setup!$B$7", "Setup!$B$8", "Setup!$B$9"


def tension(ref):
    return f'=IF({ref}="","",({HT}+{ref}/1000)*9.81*(1-{FRIC}/100))'


def module_sheet(wb, m):
    label, design, phal, role, prio, t30, fail, lever = m
    ws = wb.create_sheet(label)
    ws["A1"] = f"{label}: {design}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = f"Phalanges: {phal}.  {role}.  Blue cells: inputs.  Tensions include the hanger and the pulley friction."
    c(ws, "A4", "Date", bold=True); c(ws, "B4", None, inp=True)
    c(ws, "C4", "Temperature (°C)", bold=True); c(ws, "D4", None, inp=True)
    head(ws, 6, ["Before testing", "point 1", "point 2", "point 3", "average"], 18)
    for r, lab in ((7, "strip / leaf thickness (mm)"), (8, "strip / leaf width (mm)")):
        c(ws, f"A{r}", lab, bold=True)
        for col in "BCD":
            c(ws, f"{col}{r}", None, inp=True, fmt="0.00")
        c(ws, f"E{r}", f'=IF(COUNT(B{r}:D{r})=0,"",AVERAGE(B{r}:D{r}))', fmt="0.000")
    for r, lab in ((9, "bearing gap (mm), B4 / B8 only"), (10, "module mass (g)"),
                   (11, "resting angle, empty tendon hanger, no fingertip hanger (°)")):
        c(ws, f"A{r}", lab, bold=True)
        c(ws, f"E{r}", None, inp=True, fmt="0.0")
    c(ws, "A12", "H / K only: pin check (falls back freely? yes / no)", bold=True); c(ws, "E12", None, inp=True)
    c(ws, "A13", "Predicted tendon pull to reach 30°, no fingertip weight (N, 21 MPa)", bold=True)
    c(ws, "E13", t30, fmt="0.00", fill=RES)
    c(ws, "A14", "Predicted way of giving way", bold=True)
    c(ws, "B14", fail, wrap=True)
    ws.merge_cells("B14:G14")
    ws.row_dimensions[14].height = 30
    c(ws, "A15", "Tendon lever about the pivot (mm)", bold=True); c(ws, "E15", lever, fmt="0.00")

    # step 1
    c(ws, "A17", "STEP 1: free closing curve (no fingertip hanger, no rest block)", bold=True, fill=HEAD)
    head(ws, 18, ["Reading", "Direction", "Tendon weights added (g)", "Tension T (N)", "Angle (°)", "Notes"])
    plan = [("up", g) for g in list(range(0, 201, 20)) + list(range(250, 501, 50))]
    plan += [("down", g) for g, _ in zip(list(range(450, -1, -50)), range(10))]
    r = 19
    for i, (d, g) in enumerate(plan):
        c(ws, f"A{r}", i)
        c(ws, f"B{r}", d)
        c(ws, f"C{r}", g, inp=True, fmt="0")
        c(ws, f"D{r}", tension(f"C{r}"), fmt="0.000")
        c(ws, f"E{r}", None, inp=True, fmt="0.0")
        c(ws, f"F{r}", None, inp=True)
        r += 1
    s1_end = r - 1
    r += 1
    c(ws, f"A{r}", "Tendon weights added when the angle first reached 30° (g)", bold=True)
    c(ws, f"E{r}", None, inp=True, fmt="0")
    t30r = r
    c(ws, f"A{r + 1}", "Measured tendon pull to 30° (N)", bold=True)
    c(ws, f"E{r + 1}", tension(f"E{t30r}"), fmt="0.000", fill=RES)
    c(ws, f"A{r + 2}", "Measured ÷ predicted", bold=True)
    c(ws, f"E{r + 2}", f'=IF(E{r + 1}="","",E{r + 1}/E13)', fmt="0.00", fill=RES)
    c(ws, f"A{r + 3}", "Largest angle reached in step 1 (°)", bold=True)
    c(ws, f"E{r + 3}", f'=IF(COUNT(E19:E{s1_end})=0,"",MAX(E19:E{s1_end}))', fmt="0.0")
    meas_t30 = f"E{r + 1}"
    ratio_t30 = f"E{r + 2}"
    r += 5

    # step 2
    c(ws, f"A{r}", "STEP 2: fingertip force held (rest block in; fingertip hanger on the 44.8 mm hole)", bold=True, fill=HEAD)
    r += 1
    head(ws, r, ["Fingertip weights added (g)", "Fingertip load W (N)", "Tendon weights at lift-off (g)", "T lift-off (N)",
                 "Tendon weights at 30° (g)", "T at 30° (N)", "Tendon weights at 60° (g)", "T at 60° (N)", "Notes"])
    r += 1
    s2a = r
    for g in (50, 100, 200, 300, 500):
        c(ws, f"A{r}", g, inp=True, fmt="0")
        c(ws, f"B{r}", f'=IF(A{r}="","",({HF}+A{r}/1000)*9.81)', fmt="0.000")
        for inc, outc in (("C", "D"), ("E", "F"), ("G", "H")):
            c(ws, f"{inc}{r}", None, inp=True, fmt="0")
            c(ws, f"{outc}{r}", tension(f"{inc}{r}"), fmt="0.000")
        c(ws, f"I{r}", None, inp=True)
        r += 1
    s2b = r - 1
    r += 1
    c(ws, f"A{r}", "Largest fingertip load held at 30° with T ≤ 47 N (N)", bold=True)
    c(ws, f"F{r}", f'=IFERROR(_xlfn.MAXIFS(B{s2a}:B{s2b},F{s2a}:F{s2b},"<=47"),"")', fmt="0.00", fill=RES)
    hold = f"F{r}"
    c(ws, f"A{r + 1}", "Holds at least 2 N at 30°?", bold=True)
    c(ws, f"F{r + 1}", f'=IF(OR({hold}="",{hold}=0),"",IF({hold}>=2,"yes","no"))', fill=RES)
    hold_ok = f"F{r + 1}"
    r += 3

    # step 3
    c(ws, f"A{r}", "STEP 3: where it gives way (copy 1 / single copies last; stop above the adapter at 30°; "
                   "stop at 4.8 kg of tendon weights)", bold=True, fill=HEAD)
    ws.merge_cells(f"A{r}:H{r}")
    r += 1
    items = [("Angle held against the stop (°)", 30, "0"),
             ("Fingertip weights left on to steady it (g)", 100, "0"),
             ("Tendon weights added when it gave way, or 4800 if nothing happened (g)", None, "0"),
             ("Tension at that point (N)", "T", "0.00"),
             ("How it gave way", None, None),
             ("Palm-side collar gap before loading (mm)", None, "0.00"),
             ("Palm-side collar gap at the last load before giving way (mm)", None, "0.00"),
             ("Resting angle 1 min after unloading (°)", None, "0.0")]
    refs = {}
    for lab, v, fmt in items:
        c(ws, f"A{r}", lab, bold=True)
        if v == "T":
            c(ws, f"E{r}", tension(f"E{r - 1}"), fmt=fmt, fill=RES)
            refs["T"] = f"E{r}"
        else:
            c(ws, f"E{r}", v, inp=True, fmt=fmt)
        if lab.startswith("How"):
            refs["mode"] = f"E{r}"
            dv = DataValidation(type="list", formula1=f'"{MODES}"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"E{r}")
        r += 1
    c(ws, f"A{r}", "Gave way gradually (squash or none)?", bold=True)
    c(ws, f"E{r}", f'=IF({refs["mode"]}="","",IF(OR({refs["mode"]}="squash",{refs["mode"]}="none at 47 N"),"yes","no"))',
      fill=RES)
    refs["grad"] = f"E{r}"
    r += 2

    # step 4
    c(ws, f"A{r}", "STEP 4: spring-back (no fingertip hanger, no rest block; hold 60 s at 60°, then lift the tendon hanger)",
      bold=True, fill=HEAD)
    ws.merge_cells(f"A{r}:H{r}")
    r += 1
    head(ws, r, ["Angle (°)", "first time", "after 1,000 cycles (copy 2)"], 18)
    r += 1
    sb = {}
    for lab in ("held before release", "1 s after", "10 s after", "60 s after", "10 min after"):
        c(ws, f"A{r}", lab, bold=True)
        c(ws, f"B{r}", None, inp=True, fmt="0.0")
        c(ws, f"C{r}", None, inp=True, fmt="0.0")
        sb[lab] = r
        r += 1
    c(ws, f"A{r}", "10 min angle minus the resting angle (°)", bold=True)
    c(ws, f"B{r}", f'=IF(OR(B{sb["10 min after"]}="",$E$11=""),"",ABS(B{sb["10 min after"]}-$E$11))', fmt="0.0", fill=RES)
    c(ws, f"C{r}", f'=IF(OR(C{sb["10 min after"]}="",$E$11=""),"",ABS(C{sb["10 min after"]}-$E$11))', fmt="0.0", fill=RES)
    spring = f"B{r}"
    c(ws, f"A{r + 1}", "Within 5°?", bold=True)
    c(ws, f"B{r + 1}", f'=IF({spring}="","",IF({spring}<=5,"yes","no"))', fill=RES)
    spring_ok = f"B{r + 1}"
    r += 3

    # step 5
    c(ws, f"A{r}", "STEP 5: cycles (copy 2): 0 → 60°, fingertip weight = half the step-2 load held at 30°", bold=True, fill=HEAD)
    ws.merge_cells(f"A{r}:H{r}")
    r += 1
    head(ws, r, ["Cycles", "Resting angle (°)", "Tendon weights to reach 30° (g)", "T to 30° (N)",
                 "Change in T from the start (%)", "Notes"])
    r += 1
    s5a = r
    for n in list(range(0, 1001, 100)) + list(range(2000, 10001, 1000)):
        c(ws, f"A{r}", n, fmt="0")
        c(ws, f"B{r}", None, inp=True, fmt="0.0")
        c(ws, f"C{r}", None, inp=True, fmt="0")
        c(ws, f"D{r}", tension(f"C{r}"), fmt="0.000")
        c(ws, f"E{r}", f'=IF(OR(D{r}="",$D${s5a}=""),"",(D{r}-$D${s5a})/$D${s5a}*100)', fmt="0.0")
        c(ws, f"F{r}", None, inp=True)
        r += 1
    s5b = r - 1
    r += 1
    c(ws, f"A{r}", "Why it stopped (crack, T changed 20 %, angle changed 5°, 10,000 cycles)", bold=True)
    c(ws, f"E{r}", None, inp=True)
    c(ws, f"A{r + 1}", "Cycles reached (last row with a resting angle)", bold=True)
    c(ws, f"E{r + 1}", f'=IFERROR(_xlfn.MAXIFS(A{s5a}:A{s5b},B{s5a}:B{s5b},"<>"),"")', fmt="0", fill=RES)
    cyc = f"E{r + 1}"
    c(ws, f"A{r + 2}", "Survived 1,000 cycles?", bold=True)
    c(ws, f"E{r + 2}", f'=IF(OR({cyc}="",{cyc}=0),"",IF({cyc}>=1000,"yes","no"))', fill=RES)
    cyc_ok = f"E{r + 2}"
    ws.column_dimensions["A"].width = 58
    for col in "BCDEFGHI":
        ws.column_dimensions[col].width = 14
    return dict(meas_t30=meas_t30, ratio=ratio_t30, hold=hold, hold_ok=hold_ok, T=refs["T"], mode=refs["mode"],
                grad=refs["grad"], spring=spring, spring_ok=spring_ok, cyc=cyc, cyc_ok=cyc_ok)


def summary(wb, refs):
    ws = wb.create_sheet("Summary", 1)
    ws["A1"] = "Summary: fills itself from the module sheets"
    ws["A1"].font = Font(bold=True, size=12)
    cols = ["Module", "Design", "Pull to 30° measured (N)", "Measured ÷ predicted", "Fingertip load held at 30° (N)",
            "Holds ≥ 2 N?", "Tension when it gave way (N)", "How", "Gradual?", "Spring-back after 10 min (°)",
            "Within 5°?", "Cycles reached", "≥ 1,000 cycles?"]
    for i, h in enumerate(cols):
        c(ws, f"{chr(65 + i)}3", h, bold=True, fill=HEAD, wrap=True)
    ws.row_dimensions[3].height = 44
    for i, m in enumerate(MODULES):
        r = 4 + i
        x = refs[m[0]]
        q = f"'{m[0]}'!"
        vals = [m[0], m[1], f"={q}{x['meas_t30']}", f"={q}{x['ratio']}", f"={q}{x['hold']}", f"={q}{x['hold_ok']}",
                f"={q}{x['T']}", f'=IF({q}{x["mode"]}="","",{q}{x["mode"]})', f"={q}{x['grad']}", f"={q}{x['spring']}",
                f"={q}{x['spring_ok']}", f"={q}{x['cyc']}", f"={q}{x['cyc_ok']}"]
        for j, v in enumerate(vals):
            c(ws, f"{chr(65 + j)}{r}", v, fmt="0.00" if j in (2, 3, 4, 6, 9) else None)
    ws["A18"] = ("A design passes if it holds at least 2 N at 30°, gives way gradually, springs back within 5° and survives "
                 "1,000 cycles (copy 1 gives the first three, copy 2 the cycles). Send this workbook back and the report is "
                 "updated with each module against its prediction.")
    ws["A18"].alignment = WRAP
    ws.merge_cells("A18:M18")
    ws.row_dimensions[18].height = 30
    ws.column_dimensions["A"].width = 9
    ws.column_dimensions["B"].width = 36
    for k in range(2, 13):
        ws.column_dimensions[chr(65 + k)].width = 12


def main():
    wb = Workbook()
    readme(wb)
    setup(wb)
    refs = {m[0]: module_sheet(wb, m) for m in MODULES}
    summary(wb, refs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
