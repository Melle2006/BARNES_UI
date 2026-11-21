"""Turn the filled test workbooks into ANSYS-ready uniaxial test data (CSV).

    python3 scripts/export_ansys_csv.py

Reads results/material_tests/tension_tests_AB.xlsx and compression_test_C.xlsx (the raw
inputs only: sizes, L0 / h0, masses, gaps; the formulas are recomputed here) and writes
results/material_tests/ansys/:

  raw/<specimen>.csv              every reading as measured, engineering strain and stress
  uniaxial_tension_edge.csv       E1-1 + E2-1, fit-ready      (the main material data)
  uniaxial_tension_flat.csv       F1-1 + F2-1, fit-ready
  uniaxial_compression.csv        C1, fit-ready, negative strain and stress
  uniaxial_edge_tension_plus_compression.csv   both in one table (tension +, compression -)
  summary.csv                     E per specimen and group, and the neo-Hookean constants

Every file is two columns, engineering strain (mm/mm) and engineering stress (MPa), one
header row. "Fit-ready" means: (0, 0) kept once, readings with stress but no measurable
strain dropped (gap resolution / initial slack: they read as infinite stiffness), sorted by
strain, readings at the same strain averaged.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[1]
MT = REPO / "results" / "material_tests"
OUT = MT / "ansys"
G = 9.81
LEVER = 30          # compression rig: scale reading x 30 = force on the cylinder (already applied in the sheet)
HEADER = ["Strain [mm/mm]", "Stress [MPa]"]


def num(v):
    return v if isinstance(v, (int, float)) else None


def tension(ws):
    dims = [num(ws[f"{c}7"].value) for c in "BCD"]
    th = [num(ws[f"{c}8"].value) for c in "BCD"]
    L0 = num(ws["E16"].value)
    if None in dims or None in th or L0 is None:
        return None
    A = (sum(dims) / 3) * (sum(th) / 3)
    pts = []
    for r in range(19, 60):
        g, L = num(ws[f"B{r}"].value), num(ws[f"D{r}"].value)
        if g is None or L is None:
            continue
        pts.append(((L - L0) / L0, g / 1000 * G / A))
    return dict(area=A, L0=L0, points=pts)


def compression(ws, first_row, h0_ref):
    d = [num(ws[f"{c}7"].value) for c in "BCD"]
    plates = (num(ws["E9"].value) or 0) + (num(ws["E10"].value) or 0)
    h0r = num(ws[h0_ref].value)
    if None in d or h0r is None:
        return None
    import math
    A = math.pi * (sum(d) / 3) ** 2 / 4
    h0 = h0r - plates
    pts = []
    for r in range(first_row, first_row + 8):
        c, kg = num(ws[f"C{r}"].value), num(ws[f"E{r}"].value)
        if c is None or kg is None:
            continue
        h = c - plates
        pts.append((-(h0 - h) / h0, -kg * G / A))          # compression negative
    return dict(area=A, h0=h0, points=pts)


def fit_ready(points):
    keep = [(e, s) for e, s in points if not (abs(e) < 1e-12 and abs(s) > 1e-12)]
    groups = defaultdict(list)
    for e, s in keep:
        groups[round(e, 6)].append(s)
    out = sorted((e, sum(v) / len(v)) for e, v in groups.items())
    if (0.0, 0.0) not in out:
        out = sorted(out + [(0.0, 0.0)])
    return out


def write(path, pts):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for e, s in pts:
            w.writerow([f"{e:.6f}", f"{s:.6f}"])
    if path.parent == OUT:          # APDL (TBFT) copy: no header, space separated
        apdl = OUT / "apdl" / (path.stem + ".txt")
        apdl.parent.mkdir(parents=True, exist_ok=True)
        apdl.write_text("".join(f"{e:.6f} {s:.6f}\n" for e, s in pts))


def neo_E(points):
    """Neo-Hookean E per reading (tension: lam = 1+e; compression: lam = 1+e with e < 0),
    averaged over |strain| 2-10 %."""
    vals = []
    for e, s in points:
        if 0.02 <= abs(e) <= 0.10:
            lam = 1 + e
            vals.append(3 * s / (lam - lam ** -2))
    return sum(vals) / len(vals) if vals else None


def main():
    wbt = openpyxl.load_workbook(MT / "tension_tests_AB.xlsx", data_only=False)
    wbc = openpyxl.load_workbook(MT / "compression_test_C.xlsx", data_only=False)
    spec = {}
    for ws in wbt.worksheets[1:]:
        t = tension(ws)
        if t and len(t["points"]) > 1:
            spec[ws.title] = t
            write(OUT / "raw" / f"{ws.title}.csv", t["points"])
    comp = {}
    for ws in wbc.worksheets[1:]:
        for label, first, h0ref in (("run2", 35, "E31"), ("run1", 19, "E15")):
            c = compression(ws, first, h0ref)
            if c and len(c["points"]) > 1:
                comp[ws.title] = c
                write(OUT / "raw" / f"{ws.title}.csv", c["points"])
                break
    edge = [p for n in spec if n.startswith("E") for p in spec[n]["points"]]
    flat = [p for n in spec if n.startswith("F") for p in spec[n]["points"]]
    write(OUT / "uniaxial_tension_edge.csv", fit_ready(edge))
    write(OUT / "uniaxial_tension_flat.csv", fit_ready(flat))
    # compression: C1 only (C2's start is offset; see compression_C1_C2_from_video.md)
    c1 = comp.get("C1", {}).get("points", [])
    write(OUT / "uniaxial_compression.csv", fit_ready(c1))
    write(OUT / "uniaxial_edge_tension_plus_compression.csv", fit_ready(edge + c1))
    rows = [["Item", "Value", "Unit", "Note"]]
    for n, t in spec.items():
        rows.append([f"E {n} (tension)", f"{neo_E(t['points']):.2f}", "MPa",
                     f"area {t['area']:.3f} mm2, L0 {t['L0']} mm, {len(t['points'])} readings"])
    for n, c in comp.items():
        e = neo_E(c["points"])
        rows.append([f"E {n} (compression)", f"{e:.2f}" if e else "", "MPa",
                     f"area {c['area']:.3f} mm2, h0 {c['h0']} mm" + ("; NOT USED: offset start" if n == "C2" else "")])
    e_edge = neo_E(edge)
    e_flat = neo_E(flat)
    e_c1 = neo_E(c1)
    rows += [["E tension, printed on edge (E1-1 + E2-1, all readings 2-10 %)", f"{e_edge:.2f}", "MPa", "main value"],
             ["E tension, printed flat (F1-1 + F2-1, all readings 2-10 %)", f"{e_flat:.2f}", "MPa", ""],
             ["E compression (C1)", f"{e_c1:.2f}", "MPa", "provisional: one fast run"],
             ["Neo-Hookean initial shear modulus mu = E/3 (edge tension)", f"{e_edge / 3:.3f}", "MPa",
              "ANSYS Neo-Hookean 'Initial Shear Modulus Mu'"],
             ["Neo-Hookean incompressibility D1 for nu = 0.49", f"{6 * (1 - 2 * 0.49) / (e_edge * 1.0):.5f}",
              "1/MPa", "D1 = 2/K, K = E/(3(1-2nu)); use 0 for fully incompressible"]]
    with open(OUT / "summary.csv", "w", newline="") as f:
        csv.writer(f).writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
