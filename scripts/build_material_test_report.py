"""Experiment report on the TPU material tests (tests A, B and C).

    python scripts/build_material_test_report.py      # needs the venv with reportlab

Writes docs/report/BARNES_TPU_material_test_report.pdf and its figures in
docs/report/figures/material/. Every number is computed here from the filled workbooks
(results/material_tests/*.xlsx) through the same formulas as the workbooks and
scripts/export_ansys_csv.py.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load("bpr", REPO / "scripts" / "build_print_report.py")
M = _load("bmr", REPO / "scripts" / "build_math_report.py")
X = _load("eac", REPO / "scripts" / "export_ansys_csv.py")
P, bullets, table, figure, W = R.P, R.bullets, R.table, R.figure, R.W
eq, theory, example = M.eq, M.theory, M.example

OUT = REPO / "docs" / "report"
FIG = OUT / "figures" / "material"
PDF = OUT / "BARNES_TPU_material_test_report.pdf"
MT = REPO / "results" / "material_tests"
G = 9.81
LEVER = 30
E_PROVISIONAL = 12.0
BRACKET = (5.3, 19.3)
COL = {"F1-1": "#9ecae1", "F2-1": "#2a7ab9", "E1-1": "#f4a582", "E2-1": "#d6604d", "C1": "#4d9221", "C2": "#bbbbbb"}


# ---------------------------------------------------------------- data
def load():
    wbt = openpyxl.load_workbook(MT / "tension_tests_AB.xlsx")
    wbc = openpyxl.load_workbook(MT / "compression_test_C.xlsx")
    spec = {}
    for ws in wbt.worksheets[1:]:
        t = X.tension(ws)
        if t and len(t["points"]) > 1:
            dims = [X.num(ws[f"{c}7"].value) for c in "BCD"]
            th = [X.num(ws[f"{c}8"].value) for c in "BCD"]
            raw = []
            for r in range(19, 60):
                g, L = X.num(ws[f"B{r}"].value), X.num(ws[f"D{r}"].value)
                if g is not None and L is not None:
                    raw.append((g, L))
            t.update(dims=dims, th=th, raw=raw, kind="edge" if ws.title.startswith("E") else "flat")
            spec[ws.title] = t
    comp = {}
    for ws in wbc.worksheets[1:]:
        c = X.compression(ws, 35, "E31") or X.compression(ws, 19, "E15")
        if c and len(c["points"]) > 1:
            d = [X.num(ws[f"{x}7"].value) for x in "BCD"]
            raw = []
            for r in list(range(35, 43)):
                h, kg = X.num(ws[f"C{r}"].value), X.num(ws[f"E{r}"].value)
                if h is not None and kg is not None:
                    raw.append((ws[f"B{r}"].value, h, kg / LEVER * 1000, kg))
            c.update(d=d, raw=raw)
            comp[ws.title] = c
    return spec, comp


def e_rows(points):
    out = []
    for e, s in points:
        if abs(e) > 1e-9:
            lam = 1 + e
            out.append((e, 3 * s / (lam - lam ** -2)))
    return out


def e_window(points):
    v = [E for e, E in e_rows(points) if 0.02 <= abs(e) <= 0.10]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def e_lsq(points, lim=None):
    """Least-squares neo-Hookean E through the origin: sigma = (E/3) g(lam), g = lam - lam^-2."""
    pts = [(e, s) for e, s in points if not (abs(e) < 1e-12 and abs(s) > 1e-12)]
    if lim:
        pts = [(e, s) for e, s in pts if abs(e) <= lim]
    g = np.array([(1 + e) - (1 + e) ** -2 for e, s in pts])
    s = np.array([s for e, s in pts])
    E = 3 * float((g * s).sum() / (g * g).sum())
    pred = E / 3 * g
    ss_res = float(((s - pred) ** 2).sum())
    ss_tot = float(((s - s.mean()) ** 2).sum())
    return E, 1 - ss_res / ss_tot, math.sqrt(ss_res / len(s))


def gent_shore(sh):
    return 0.0981 * (56 + 7.66 * sh) / (0.137505 * (254 - 2.54 * sh))


# ---------------------------------------------------------------- figures
def fig_curves(spec, comp, E_edge, E_comp):
    FIG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.4))
    lam = np.linspace(1, 1.2, 100)
    for n, t in spec.items():
        e = [p[0] * 100 for p in t["points"]]
        s = [p[1] for p in t["points"]]
        ax[0].plot(e, s, "o", color=COL[n], ms=4.5, label=f"{n} ({t['kind']})")
    ax[0].plot((lam - 1) * 100, E_edge / 3 * (lam - lam ** -2), "-", color="k", lw=1.3,
               label=f"neo-Hookean, E = {E_edge:.1f} MPa (edge)")
    ax[0].axvspan(2, 10, color="#2a7ab9", alpha=0.07)
    ax[0].set(xlabel="engineering strain (%)", ylabel="engineering stress (MPa)", title="Tests A and B: tension",
              xlim=(0, 20), ylim=(0, 3.3))
    ax[0].legend(fontsize=7.5, frameon=False)
    lc = np.linspace(0.86, 1, 100)
    for n, c in comp.items():
        e = [-p[0] * 100 for p in c["points"]]
        s = [-p[1] for p in c["points"]]
        ax[1].plot(e, s, "s" if n == "C1" else "x", color=COL[n], ms=5,
                   label=f"{n}" + (" (not used: offset start)" if n == "C2" else ""))
    ax[1].plot((1 - lc) * 100, -(E_comp / 3) * (lc - lc ** -2), "-", color="k", lw=1.3,
               label=f"neo-Hookean, E = {E_comp:.1f} MPa (C1)")
    ax[1].plot((1 - lc) * 100, -(E_edge / 3) * (lc - lc ** -2), "--", color="#d6604d", lw=1.1,
               label=f"tension E = {E_edge:.1f} MPa, for comparison")
    ax[1].axvspan(2, 10, color="#2a7ab9", alpha=0.07)
    ax[1].set(xlabel="compressive strain (%)", ylabel="compressive stress (MPa)", title="Test C: compression",
              xlim=(0, 13), ylim=(0, 4.5))
    ax[1].legend(fontsize=7.5, frameon=False)
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG / "curves.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


def fig_erows(spec, comp):
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for n, t in list(spec.items()) + [("C1", comp["C1"])]:
        r = e_rows(t["points"])
        ax.plot([abs(e) * 100 for e, E in r], [E for e, E in r], "o-", color=COL[n], ms=4, lw=0.8, label=n)
    ax.axvspan(2, 10, color="#2a7ab9", alpha=0.07)
    ax.text(6, 2, "readings averaged (2–10 %)", ha="center", fontsize=8, color="#2a7ab9")
    ax.axhspan(*BRACKET, color="#999999", alpha=0.08)
    ax.text(17.5, 12.3, "range assumed before\nthe tests (5.3–19.3)", fontsize=7.5, color="#666666", ha="center")
    ax.axhline(E_PROVISIONAL, color="#999999", lw=0.8, ls=":")
    ax.set(xlabel="|strain| (%)", ylabel="E for the reading (MPa)", ylim=(0, 60), xlim=(0, 20))
    ax.legend(fontsize=7.5, ncol=5, frameon=False, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG / "e_per_reading.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


def fig_compression_rig():
    """Schematic of the lever compression rig (generic; replaced by the drawing from the setup video)."""
    import matplotlib.patches as mpt
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.add_patch(mpt.Rectangle((-5, -6), 120, 4, fc="#c9a77c", ec="k", lw=0.6, hatch="///"))
    ax.add_patch(mpt.Polygon([[0, -2], [-3, -2], [0, 4], [3, -2]], fc="#777777", ec="k"))
    ax.add_patch(mpt.Rectangle((-2, 4), 104, 2.5, fc="#b0b8c0", ec="k", lw=0.7))
    ax.add_patch(mpt.Rectangle((8, -2), 6, 3, fc="#9aa3ad", ec="k", lw=0.6))
    ax.add_patch(mpt.Rectangle((9, 1), 4, 3, fc="#5585c8", ec="k", lw=0.6))
    ax.add_patch(mpt.FancyBboxPatch((88, -2), 20, 4, boxstyle="round,pad=0.4", fc="#dddddd", ec="k"))
    ax.annotate("", (11, 10), (11, 6.8), arrowprops=dict(arrowstyle="<->", color="#b5481d"))
    ax.text(0, 9, "fulcrum", fontsize=8)
    ax.text(12, 11, "cylinder at distance a", fontsize=8, color="#1f4e8c")
    ax.text(84, 9, "scale at distance b ≈ 30 a", fontsize=8)
    ax.annotate("", (0, 13), (11, 13), arrowprops=dict(arrowstyle="<->", color="k", lw=0.7))
    ax.annotate("", (0, 16), (98, 16), arrowprops=dict(arrowstyle="<->", color="k", lw=0.7))
    ax.text(5, 13.6, "a", fontsize=8, ha="center")
    ax.text(49, 16.6, "b", fontsize=8, ha="center")
    ax.text(50, -10.5, "Force on the cylinder F = (b / a) × scale reading × g = 30 × m × g   "
            "(schematic: proportions to be matched to the setup video)", ha="center", fontsize=8, color="#b5481d")
    ax.set_xlim(-8, 118)
    ax.set_ylim(-13, 19)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    p = FIG / "compression_rig_schematic.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


# ---------------------------------------------------------------- story
def story(spec, comp):
    E_spec = {n: e_window(t["points"])[0] for n, t in spec.items()}
    n_spec = {n: e_window(t["points"])[1] for n, t in spec.items()}
    lsq = {n: e_lsq(t["points"]) for n, t in spec.items()}
    edge_pts = [p for n, t in spec.items() if t["kind"] == "edge" for p in t["points"]]
    flat_pts = [p for n, t in spec.items() if t["kind"] == "flat" for p in t["points"]]
    E_edge, n_edge = e_window(edge_pts)
    E_flat, n_flat = e_window(flat_pts)
    E_edge_lsq, r2_edge, rms_edge = e_lsq(edge_pts)
    E_comp, n_comp = e_window(comp["C1"]["points"])
    E_comp_lsq, r2_comp, rms_comp = e_lsq(comp["C1"]["points"])
    E_c2, _ = e_window(comp["C2"]["points"])
    vals = np.array(list(E_spec.values()))
    mean4, sd4 = float(vals.mean()), float(vals.std(ddof=1))
    shore = gent_shore(90)
    k = E_edge / E_PROVISIONAL
    mu = E_edge / 3
    K = E_edge / (3 * (1 - 2 * 0.49))
    d1 = 2 / K
    curves = fig_curves(spec, comp, E_edge, E_comp)
    erows = fig_erows(spec, comp)
    setup_dir = REPO / "docs" / "figures" / "specimen_tests"

    s = [P("BARNES finger joints: SUNLU TPU 90A material tests", "title"),
         P("Experiment report: tensile tests on flat- and edge-printed specimens (tests A, B) and compression of "
           "printed cylinders (test C), with the analysis, uncertainties and conclusions", "sub"),
         P("Data: results/material_tests/ · generated by scripts/build_material_test_report.py", "sub"),
         Spacer(1, 6 * mm)]

    # 1 aim
    s += [P("1. Aim", "h1"),
          P("To measure the elastic modulus E of the SUNLU TPU 90A filament as printed, in the two print directions "
            "the joints use, in tension and in compression, so that the joint analyses (run at a provisional "
            f"{E_PROVISIONAL:.0f} MPa, bracket {BRACKET[0]}–{BRACKET[1]} MPa) can be put on a measured basis and the "
            "material can be given to ANSYS as hyperelastic test data. SUNLU publishes no modulus.")]

    # 2 theory
    s += [P("2. Theory", "h1"), P("2.1 Engineering strain and stress", "h2")]
    s += theory(
        "Each reading gives a gauge length L (or a cylinder height h) and a load. Engineering quantities refer "
        "to the original size, which is what ANSYS expects for hyperelastic test data:",
        r"$\varepsilon = \frac{L - L_0}{L_0}, \qquad \lambda = 1 + \varepsilon, \qquad \sigma = \frac{F}{A_0}, \qquad F = m\,g",
        "with L₀ the gauge length under the zero load, A₀ the measured cross-section (width × thickness for the "
        "dog-bones, height × thickness for the strips, πd²/4 for the cylinders), m the added mass and g = 9.81 m/s².")
    s += [P("2.2 The neo-Hookean model", "h2")]
    s += theory(
        "TPU is a rubber-like solid: nearly incompressible and non-linear. The analyses model it as neo-Hookean, "
        "the simplest hyperelastic law, with one constant, the shear modulus μ:",
        r"$W = \frac{\mu}{2}\,(I_1 - 3), \qquad I_1 = \lambda_1^2 + \lambda_2^2 + \lambda_3^2",
        "In a uniaxial test of an incompressible solid λ₁ = λ, λ₂ = λ₃ = λ^(-1/2), and the engineering (nominal) "
        "stress is dW/dλ:",
        r"$\sigma = \mu\,\left(\lambda - \lambda^{-2}\right) = \frac{E}{3}\left(\lambda - \lambda^{-2}\right), \qquad E = 3\mu",
        "At small strain λ − λ⁻² ≈ 3ε, so σ ≈ Eε (Hooke's law). The same formula covers compression (λ < 1, σ < 0). "
        "Solving it for E gives one value per reading:",
        r"$E_i = \frac{3\,\sigma_i}{\lambda_i - \lambda_i^{-2}}",
        "and the specimen's E is the average of E_i over the readings between 2 % and 10 % strain: above the "
        "resolution of the gap readings, and inside the range the joints work in (the designs are held to 20 %). "
        "A straight-line slope of σ against ε would read about 10 % low, because the neo-Hookean curve bends over.")
    s += [P("2.3 Least-squares fit (check)", "h2")]
    s += theory(
        "As a check, E is also fitted to every reading at once. The model is linear in E, so the least-squares "
        "value through the origin is closed-form:",
        r"$E_{\mathrm{LSQ}} = 3\,\frac{\sum_i g_i\,\sigma_i}{\sum_i g_i^2}, \qquad g_i = \lambda_i - \lambda_i^{-2}",
        "with R² and the RMS residual showing how well one constant describes the whole curve.")
    s += [P("2.4 Lever (compression rig)", "h2")]
    s += theory(
        "The compression rig loads the cylinder through a lever: with the cylinder at distance a from the fulcrum "
        "and the scale at distance b, moments about the fulcrum give",
        r"$F_{\mathrm{cyl}}\,a = F_{\mathrm{scale}}\,b \;\Rightarrow\; F_{\mathrm{cyl}} = \frac{b}{a}\,m_{\mathrm{scale}}\,g = 30\,m_{\mathrm{scale}}\,g")
    s += [P("2.5 Constants for ANSYS, and the hardness cross-check", "h2")]
    s += theory(
        "ANSYS's neo-Hookean model takes μ and an incompressibility parameter d = 2/K, with the bulk modulus K "
        "from E and Poisson's ratio ν:",
        r"$\mu = \frac{E}{3}, \qquad K = \frac{E}{3\,(1-2\nu)}, \qquad d = \frac{2}{K}",
        "Gent's empirical relation turns a Shore A hardness S into an estimate of Young's modulus (MPa), a "
        "rough independent check:",
        r"$E \approx \frac{0.0981\,(56 + 7.66\,S)}{0.137505\,(254 - 2.54\,S)}")

    # 3 apparatus and specimens
    s += [PageBreak(), P("3. Apparatus and specimens", "h1")]
    s += [P("Specimens were printed on a Bambu Lab A1 (0.4 mm nozzle, 0.2 mm layers, 100 % infill) from the same "
            "SUNLU TPU 90A spool and print profile as the joint modules, and labelled by an engraved code. One copy "
            "of each was tested.")]
    rows = [["Specimen", "Test", "Shape", "Print direction", "Measured section", "A₀ (mm²)", "L₀ / h₀ (mm)"]]
    for n, t in spec.items():
        dims = t["dims"]
        rows.append([n, "A" if t["kind"] == "flat" else "B",
                     "1BA dog-bone (ISO 527-2)" if t["kind"] == "flat" else "strip 80 × 6 mm",
                     "flat" if t["kind"] == "flat" else "on edge (as the joint leaves)",
                     f"{np.mean(dims):.2f} × {np.mean(t['th']):.2f} mm", f"{t['area']:.2f}", f"{t['L0']:.1f}"])
    for n, c in comp.items():
        rows.append([n, "C", "cylinder", "on a flat end", f"Ø {np.mean(c['d']):.2f} mm", f"{c['area']:.2f}",
                     f"{c['h0']:.1f}"])
    s += [table(rows, widths=[17 * mm, 11 * mm, 34 * mm, 34 * mm, 30 * mm, 18 * mm, W - 144 * mm])]
    s += [P("Sections are the means of three caliper readings (0.1 mm resolution). L₀ is the gauge-mark spacing "
            "under the zero load; h₀ the cylinder height.", "cap")]
    s += [P("3.1 Tension (tests A and B)", "h2"),
          P("A long aluminium extrusion, held in a bench vice, overhung the bench edge. A C-clamp at its far end "
            "gripped the top of the specimen, which hung free; a steel angle bracket clamped to its lower end was "
            "the bottom grip and the weight hanger (an earlier version used a wooden arm with a bolt). Loads were "
            "added in 100 g (1.0 mm specimens) or 200 g (2.0 mm) steps, and the gap between two marks about 20 mm "
            "apart was read at each step.")]
    s += figure(FIG / "tension_rig_asbuilt.png", "Tension rig as built (diagram from the setup video; not to scale).",
                max_h=80 * mm)
    s += figure(FIG / "photo_tension_rig.jpg", "The tension rig (frame from the setup video).", max_h=62 * mm)
    s += figure(FIG / "tension_strip.png", "Loading sequence (frames of docs/report/figures/material/tension_rig.gif): "
                "empty hanger, half load, full load.", max_h=45 * mm)
    s += [P("3.2 Compression (test C)", "h2"),
          P("An aluminium extrusion lever was hinged on a steel bracket on a stack of wooden blocks; its far end turned "
            "down into a leg standing on a kitchen scale (0.1 g). The cylinder sat on the lever next to the hinge, "
            "under the nose of a bench press. With the cylinder at a from the hinge and the leg at b ≈ 30a, the "
            "scale carries 1/30 of the force on the cylinder. The compression was read on the press and called out "
            "aloud while the scale was filmed; the values were taken from the videos afterwards (the calls by "
            "speech-to-text, the scale from the frames at each call).")]
    s += figure(FIG / "compression_rig_asbuilt.png", "Compression rig as built (diagram from the setup video; not to "
                "scale; the lever's tilt and the compression are exaggerated).", max_h=82 * mm)
    s += figure(FIG / "photo_compression_rig.jpg", "The compression rig (frame from the setup video): lever, hinge "
                "bracket on the wooden blocks, press above the cylinder, leg on the scale (left).", max_h=62 * mm)
    s += figure(FIG / "compression_strip.png", "Loading sequence (frames of docs/report/figures/material/"
                "compression_rig.gif): press touching, 5 %, 10 % (exaggerated).", max_h=45 * mm)

    # 4 procedure
    s += [P("4. Procedure", "h1")]
    s += bullets([
        "Measure each specimen's section at three points; mark the tensile specimens with two thin lines about "
        "20 mm apart on the narrow part (strips: the middle 40 mm).",
        "Tension: hang the specimen with the empty bag; condition (load to ~15 % strain and unload, three times); "
        "record L₀ under the empty bag; add load in steps, waiting 30 s at each, and record the total added mass and "
        "the mark gap, to at least 15 % strain.",
        "Compression: place the cylinder on the lever under the press, zero the scale, press down, calling out the "
        "compression read on the press while filming the scale.",
        "Compute ε, σ and E_i for every reading; average E_i over 2–10 % strain; fit E_LSQ as a check.",
    ])
    s += [P("Departures from the written procedure: one copy of each specimen instead of three; the conditioning "
            "loads recorded (0.045–0.06 kg) are far below the ~1–2 kg intended, so the specimens were in effect not "
            "conditioned; the compression rig (lever, called-out compression, continuous loading) differs from the "
            "written one (press, held 0.2 mm steps).", "cap")]

    # 5 results
    s += [PageBreak(), P("5. Results", "h1")]
    s += figure(curves, "Engineering stress against strain, with the neo-Hookean curves at the measured moduli. "
                        "Shaded: the 2–10 % band used for E.", max_h=85 * mm)
    rows = [["Specimen", "Readings", "In 2–10 %", "E, 2–10 % average (MPa)", "E, LSQ all readings (MPa)", "R²", "RMS residual (MPa)"]]
    for n, t in spec.items():
        E_l, r2, rms = lsq[n]
        rows.append([n, str(len(t["points"])), str(n_spec[n]), f"{E_spec[n]:.2f}", f"{E_l:.2f}", f"{r2:.3f}", f"{rms:.3f}"])
    rows.append(["Edge (E1-1 + E2-1)", str(len(edge_pts)), str(n_edge), f"<b>{E_edge:.2f}</b>", f"{E_edge_lsq:.2f}",
                 f"{r2_edge:.3f}", f"{rms_edge:.3f}"])
    rows.append(["Flat (F1-1 + F2-1)", str(len(flat_pts)), str(n_flat), f"{E_flat:.2f}", f"{e_lsq(flat_pts)[0]:.2f}",
                 f"{e_lsq(flat_pts)[1]:.3f}", f"{e_lsq(flat_pts)[2]:.3f}"])
    rows.append(["C1 (compression)", str(len(comp["C1"]["points"])), str(n_comp), f"<b>{E_comp:.2f}</b>",
                 f"{E_comp_lsq:.2f}", f"{r2_comp:.3f}", f"{rms_comp:.3f}"])
    rows.append(["C2 (compression, not used)", str(len(comp["C2"]["points"])), "", f"{E_c2:.2f}", "", "", ""])
    s += [table(rows, widths=[38 * mm, 16 * mm, 16 * mm, 30 * mm, 30 * mm, 14 * mm, W - 144 * mm])]
    s += [P("Group values pool all readings of the group in the 2–10 % band. LSQ: least-squares neo-Hookean fit "
            "through every reading (stress with no measurable strain excluded).", "cap")]
    s += figure(erows, "E for each reading. A constant E means the neo-Hookean model fits; the grey band is the "
                       "range assumed before the tests, the dotted line the provisional 12 MPa.", max_h=72 * mm)

    # 6 worked calculation
    t = spec["E1-1"]
    g_, L = next((g, L) for g, L in t["raw"] if (L - t["L0"]) / t["L0"] >= 0.045)
    eps = (L - t["L0"]) / t["L0"]
    F = g_ / 1000 * G
    sig = F / t["area"]
    lam = 1 + eps
    Ei = 3 * sig / (lam - lam ** -2)
    cr = comp["C1"]["raw"][3]
    hc = cr[1]
    epsc = (comp["C1"]["h0"] - hc) / comp["C1"]["h0"]
    Fc = cr[3] * G
    sigc = Fc / comp["C1"]["area"]
    lamc = 1 - epsc
    Ec = 3 * sigc / (lamc ** -2 - lamc)
    s += [P("6. Calculations", "h1")]
    s += example("one tension reading (E1-1)", [
        f"Section {np.mean(t['dims']):.2f} × {np.mean(t['th']):.2f} mm → A₀ = {t['area']:.2f} mm²; L₀ = {t['L0']:.1f} mm",
        f"Added mass {g_:.0f} g → F = {g_ / 1000:.3f} × 9.81 = {F:.3f} N; σ = {F:.3f} / {t['area']:.2f} = {sig:.4f} MPa",
        f"Gap L = {L:.1f} mm → ε = ({L:.1f} − {t['L0']:.1f}) / {t['L0']:.1f} = {eps:.4f}; λ = {lam:.4f}",
        f"E_i = 3 × {sig:.4f} / ({lam:.4f} − {lam:.4f}⁻²) = 3 × {sig:.4f} / {lam - lam ** -2:.4f} = <b>{Ei:.2f} MPa</b>",
        f"(Hooke's law would give σ/ε = {sig / eps:.2f} MPa: close at this strain.)"])
    s += example("one compression reading (C1)", [
        f"Ø {np.mean(comp['C1']['d']):.2f} mm → A₀ = π × {np.mean(comp['C1']['d']):.2f}² / 4 = {comp['C1']['area']:.2f} mm²; "
        f"h₀ = {comp['C1']['h0']:.1f} mm",
        f"Compression called {cr[0]} mm → h = {hc:.2f} mm; ε = {epsc:.4f}; λ = {lamc:.4f}",
        f"Scale {cr[2]:.1f} g × 30 = {cr[3]:.3f} kg → F = {Fc:.1f} N; σ = {sigc:.3f} MPa",
        f"E_i = 3σ / (λ⁻² − λ) = 3 × {sigc:.3f} / {lamc ** -2 - lamc:.4f} = <b>{Ec:.2f} MPa</b>"])
    s += example("ANSYS constants from the edge result", [
        f"μ = E/3 = {E_edge:.2f} / 3 = <b>{mu:.3f} MPa</b>",
        f"ν = 0.49: K = {E_edge:.2f} / (3 × 0.02) = {K:.1f} MPa; d = 2/K = <b>{d1:.5f} MPa⁻¹</b> (d = 0: incompressible)",
        f"Scale factor for the joint analyses: {E_edge:.2f} / {E_PROVISIONAL:.0f} = <b>{k:.2f}</b>"])

    # 7 uncertainty
    dL = 0.1 / math.sqrt(12)
    de_reading = math.sqrt(2) * dL / 20
    dA_t = 0.1 / math.sqrt(12) / 1.0
    s += [P("7. Uncertainty", "h1")]
    s += theory(
        "For E ∝ σ/ε with σ = mg/(wt), the relative uncertainties add in quadrature:",
        r"$\frac{\delta E}{E} \approx \sqrt{\left(\frac{\delta\varepsilon}{\varepsilon}\right)^2 + \left(\frac{\delta t}{t}\right)^2"
        r" + \left(\frac{\delta w}{w}\right)^2 + \left(\frac{\delta m}{m}\right)^2}")
    rows = [["Source", "Size", "Effect on E"],
            ["Gap readings, 0.1 mm resolution", f"±{dL:.3f} mm per reading (uniform); ε from two readings: ±{de_reading * 100:.2f} % strain",
             f"±{de_reading / 0.05 * 100:.0f} % on one reading at 5 % strain; ~±{de_reading / 0.05 * 100 / math.sqrt(6):.0f} % on the 2–10 % average"],
            ["Thickness, 0.1 mm resolution on ~1–2 mm", f"±{dA_t * 100:.1f} % (1 mm) to ±{dA_t * 50:.1f} % (2 mm)", "same, directly"],
            ["Width / height, 0.1 mm on 5–6 mm", "±0.5 %", "same, directly"],
            ["Masses, ±1 g", "<±1 % above 100 g", "negligible"],
            ["No conditioning (Mullins effect)", "first-stretch stiffening, typically 10–20 % at small strain", "E reads high by up to that much"],
            ["Specimen-to-specimen scatter (4 tension specimens)", f"mean {mean4:.1f} MPa, standard deviation {sd4:.1f} MPa",
             f"±{sd4 / mean4 * 100:.0f} % (dominant)"],
            ["Compression: lever ratio, continuous loading, values read from video", "ratio not calibrated; scale moving at the calls",
             "not quantified; C1 is provisional"]]
    s += [table(rows, widths=[52 * mm, 62 * mm, W - 114 * mm])]
    s += [P(f"With one specimen per condition, the spread between specimens ({sd4 / mean4 * 100:.0f} %) is the best "
            f"measure of the uncertainty: E (edge) = {E_edge:.1f} ± {sd4:.1f} MPa (one standard deviation).", "cap")]

    # 8 discussion
    s += [PageBreak(), P("8. Discussion", "h1")]
    s += bullets([
        f"<b>Tension modulus.</b> The four specimens give {', '.join(f'{v:.1f}' for v in vals)} MPa; the edge pair, "
        f"which matters for the joints, {E_edge:.1f} MPa. This is above the bracket assumed before the tests "
        f"({BRACKET[0]}–{BRACKET[1]} MPa) and {k:.2f} times the provisional {E_PROVISIONAL:.0f} MPa.",
        f"<b>Print direction.</b> Flat ({E_flat:.1f} MPa) and edge ({E_edge:.1f} MPa) differ by "
        f"{abs(E_flat - E_edge) / E_edge * 100:.0f} %, well inside the specimen scatter: at this resolution the printed TPU "
        "behaves as isotropic in tension, which is how the analyses treat it.",
        f"<b>Cross-check.</b> Gent's relation gives {shore:.1f} MPa for Shore 90A, within "
        f"{abs(shore - E_edge) / E_edge * 100:.0f} % of the edge result: the measurement is plausible.",
        f"<b>Model fit.</b> The neo-Hookean curve describes the edge readings with R² = {r2_edge:.3f} up to about 15 % strain "
        "(figure, table): one constant is enough for the joints, whose strain is held below 20 %. The E per reading is high "
        "at the first readings (below 2 %), where one 0.1 mm step of the gap is a large share of the stretch; those are "
        "outside the averaging band.",
        f"<b>Compression.</b> C1 gives {E_comp:.1f} MPa, {E_comp / E_edge:.2f} times the tension value. A short cylinder "
        "(height ≈ diameter) reads stiff when friction holds its ends, and C1 was loaded continuously, not in held steps, "
        f"so part of the difference is the test. C2 ({E_c2:.0f} MPa) has an offset start (83 N at the first 0.1 mm call), "
        "most likely from zeroing the length gauge after loading began, and is not used. The compression was read "
        "from the press travel, which also includes the small give of the lever, hinge and scale; that makes the "
        "measured compression slightly too large and E slightly too low, so it does not explain the higher value.",
        "<b>Not conditioned.</b> The first stretch of a TPU is stiffer than later ones; the data include that, so the "
        "moduli may read up to 10–20 % high for a joint that has been cycled. This is inside the specimen scatter.",
    ])

    # 9 conclusions
    s += [P("9. Conclusions", "h1")]
    s += bullets([
        f"<b>E = {E_edge:.1f} ± {sd4:.1f} MPa</b> for the SUNLU TPU 90A printed on edge, in tension (the value to use for "
        f"the joints); {E_flat:.1f} MPa printed flat. Neo-Hookean μ = {mu:.2f} MPa; d = {d1:.5f} MPa⁻¹ for ν = 0.49.",
        "Print direction makes no measurable difference in tension at this resolution.",
        f"Compression: {E_comp:.1f} MPa (C1), provisional; use it for the bearing designs (B4, B8).",
        f"The joint analyses scale by {k:.2f}: torques, forces, capacities and return margins rise by that factor, strains "
        "and ranges do not change (print-decision report, section 0). Softer Type B joints now hold the finger straight; the "
        "free B5 t2.0 deep reaches the servo's tension at 0°; the pinned versions still hold more in a bent finger.",
        "ANSYS-ready uniaxial data and constants: results/material_tests/ansys/ (CSV, APDL text, a material macro).",
    ])
    s += [P("Recommendations", "h2")]
    s += bullets([
        "If the numbers ever need tightening: test the other two copies of each specimen, condition before measuring, "
        "and read the gap from photos to 0.02 mm.",
        "Compression: one run with held 0.2 mm steps, the gauge zeroed with the press touching, and the 30:1 ratio "
        "checked with a known weight.",
    ])

    # appendix
    s += [PageBreak(), P("Appendix: raw readings", "h1")]
    for n, t in spec.items():
        rows = [["Added mass (g)", "Gap L (mm)", "ε", "σ (MPa)", "E_i (MPa)"]]
        for g, L in t["raw"]:
            e_ = (L - t["L0"]) / t["L0"]
            sg = g / 1000 * G / t["area"]
            lam_ = 1 + e_
            Ei_ = 3 * sg / (lam_ - lam_ ** -2) if e_ > 0 else None
            rows.append([f"{g:.0f}", f"{L:.2f}", f"{e_:.4f}", f"{sg:.3f}", "–" if Ei_ is None else f"{Ei_:.1f}"])
        s += [P(f"{n} (A₀ = {t['area']:.2f} mm², L₀ = {t['L0']:.1f} mm)", "h2"),
              table(rows, widths=[W / 5] * 5)]
    for n, c in comp.items():
        rows = [["Compression called (mm)", "h (mm)", "Scale (g)", "Force on cylinder (N)", "ε", "σ (MPa)"]]
        for d_, h, gs, kg in c["raw"]:
            e_ = (c["h0"] - h) / c["h0"]
            rows.append([f"{d_}", f"{h:.2f}", f"{gs:.1f}", f"{kg * G:.1f}", f"{e_:.4f}", f"{kg * G / c['area']:.3f}"])
        s += [P(f"{n} (A₀ = {c['area']:.2f} mm², h₀ = {c['h0']:.1f} mm)" + (" — not used" if n == "C2" else ""), "h2"),
              table(rows, widths=[W / 6] * 6)]
    return s


def build():
    spec, comp = load()
    FIG.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(PDF), pagesize=R.A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title="BARNES UI — TPU material tests", author="BARNES UI")

    def foot(c, d):
        c.saveState()
        c.setFont("DV", 7.5)
        c.setFillColor(R.MUTED)
        c.drawString(15 * mm, 9 * mm, "BARNES UI — SUNLU TPU 90A material tests")
        c.drawRightString(R.A4[0] - 15 * mm, 9 * mm, f"page {d.page}")
        c.restoreState()

    doc.build(story(spec, comp), onFirstPage=foot, onLaterPages=foot)
    print(PDF)


if __name__ == "__main__":
    build()
