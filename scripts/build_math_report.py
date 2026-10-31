"""Build the methods companion to the print-decision report: every formula used in
the analyses, where it lives in the code, a worked example with the project's own
numbers, and the decision it feeds.

    python scripts/build_math_report.py

Writes docs/report/BARNES_math_methods.pdf, with equation images in
docs/report/figures/math/. Worked examples are computed here from the same
formulas and inputs the analysis scripts use, so they stay consistent with them.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, PageBreak, SimpleDocTemplate, Spacer  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
spec = importlib.util.spec_from_file_location("bpr", REPO / "scripts" / "build_print_report.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
import tendon_routing_analysis as T  # noqa: E402

P, bullets, table, figure, link, S, W = R.P, R.bullets, R.table, R.figure, R.link, R.S, R.W
OUT = REPO / "docs" / "report"
MATH = OUT / "figures" / "math"
PDF = OUT / "BARNES_math_methods.pdf"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def eq(tex, size=13.5):
    """A display equation, rendered by matplotlib's mathtext and cached by content."""
    MATH.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{tex}|{size}".encode()).hexdigest()[:12]
    path = MATH / f"eq_{key}.png"
    if not path.exists():
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${tex}$", fontsize=size, color="#1d2430")
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.04, transparent=True)
        plt.close(fig)
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(str(path)).getSize()
    w, h = iw / 300 * 72, ih / 300 * 72
    if w > W - 12 * mm:
        h *= (W - 12 * mm) / w
        w = W - 12 * mm
    img = Image(str(path), width=w, height=h)
    img.hAlign = "CENTER"
    return [Spacer(1, 2), img, Spacer(1, 4)]


def code(*paths):
    return "<b>Where in the code:</b> " + ", ".join(link(p) for p in paths)


def example(title, lines):
    """A boxed worked example."""
    rows = [[f"<b>Worked example: {title}</b>"]] + [[ln] for ln in lines]
    t = table(rows, widths=[W], header=False, zebra=False)
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7fb")),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9fb6d4")),
                           ("GRID", (0, 0), (-1, -1), 0, colors.white),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 2.5)]))
    return [Spacer(1, 3), t, Spacer(1, 6)]


def h1(t):
    return P(t, "h1")


def h2(t):
    return P(t, "h2")


def csv_rows(path, **match):
    with open(REPO / path) as f:
        return [r for r in csv.DictReader(f) if all(r.get(k) == v for k, v in match.items())]


# ---------------------------------------------------------------------------
# inputs used by the worked examples (the same files the analyses read)
# ---------------------------------------------------------------------------
E12 = 12.0
HOOK = 44.8
FLEX = T.TYPE_B_FLEX["PIP"]
b3 = csv_rows("results/tendon_routing/type_b_inputs/B3_dual_leaf.csv", variant="B3_t200_w30", joint="PIP")[0]
b5 = csv_rows("results/tendon_routing/type_b_inputs/B5_crossed_strip.csv", variant="B5_t200_a45", joint="PIP")[0]
r2 = {r["variant"]: r for r in csv_rows("TYPE B/round2/variants_summary.csv", joint="PIP")}
r2d = {r["variant"]: r for r in csv_rows("TYPE B/round2/deep_offset/variants_summary.csv", joint="PIP")}
fea = {}
for p in (REPO / "TYPE B/round2/fea/results").glob("*.json"):
    j = json.loads(p.read_text())
    fea[(j["variant"], j["offset"], j["angle"])] = j
a8 = json.loads((REPO / "results/a8_collared/cases/collared_2T_w1.2_h2.4_s2.75.json").read_text())
a8conv = {h: json.loads((REPO / f"results/a8_mesh_convergence/h{h}/cases/print_2T_w1.2_h2.4_s2.75.json").read_text())
          for h in ("0.5", "0.3") if (REPO / f"results/a8_mesh_convergence/h{h}/cases/print_2T_w1.2_h2.4_s2.75.json").exists()}
a8base = json.loads((REPO / "results/a8_index_pip_printable/cases/print_2T_w1.2_h2.4_s2.75.json").read_text())


def euler_b3():
    t, w, n, L = float(b3["t_mm"]), float(b3["w_mm"]), int(b3["n"]), float(b3["flex_len_mm"])
    I = w * t ** 3 / 12
    return dict(t=t, w=w, n=n, L=L, I=I, P=n * 4 * math.pi ** 2 * E12 * I / L ** 2)


def euler_b5():
    t, w, Ls, a = float(b5["t_mm"]), float(b5["w_mm"]), float(b5["strip_len_mm"]), float(b5["angle"])
    I = w * t ** 3 / 12
    c = math.cos(math.radians(a / 2))
    return dict(t=t, w=w, Ls=Ls, a=a, I=I, c=c, P=4 * c * 4 * math.pi ** 2 * E12 * I / Ls ** 2)


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def fig_levers():
    th = np.radians(np.linspace(0.5, 85, 200))
    d0, d1 = 1.93, 3.40
    Rr = float(r2d["B4_t100_a60_deep"]["roll_r_mm"])
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(np.degrees(th), T.arc_moment_arm(th, FLEX, d0), color="#1f5fa8", label="bending joint (B3, B6, B1 full notch), d = 1.93")
    ax.plot(np.degrees(th), T.pin_moment_arm(th, FLEX / 2, FLEX / 2, d0), color="#1f5fa8", ls="--", label="fixed centre (B5, B8 y0, B9), d = 1.93")
    ax.plot(np.degrees(th), T.pin_moment_arm(th, FLEX / 2, FLEX / 2, d1), color="#c2571a", ls="--", label="fixed centre, deep tendon d = 3.40")
    ax.plot(np.degrees(th), d1 - Rr * np.sin(th / 2), color="#2a8a4a", label=f"rolling (B4 deep, R = {Rr:.2f}), d = 3.40")
    ax.axhline(0, color="k", lw=0.6)
    ax.set(xlabel="PIP flexion θ (deg)", ylabel="tendon lever r (mm)", title="Tendon lever about the joint, PIP (section 3)")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = MATH / "levers.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


def fig_euler():
    e = euler_b3()
    t = np.linspace(0.8, 2.4, 100)
    P_ = e["n"] * 4 * math.pi ** 2 * E12 * e["w"] * t ** 3 / 12 / e["L"] ** 2
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.plot(t, P_, color="#1f5fa8", label="Euler, fixed–fixed: 2 leaves, w 3.0 mm, L 7.55 mm")
    f = fea.get(("B3_t200_w30", "as-built", 0.0))
    if f and f.get("capacity_T"):
        ax.plot([2.0], [f["capacity_T"]], "o", color="#c2571a", label=f"FEA, B3_t200_w30 at 0°: {f['capacity_T']:.1f} N")
        ax.plot([2.0], [e["P"]], "s", color="#1f5fa8", mfc="white")
    ax.set(xlabel="leaf thickness t (mm)", ylabel="tendon tension at buckling (N), E = 12 MPa",
           title="Hand estimate against FEA: a thin leaf in compression (section 4)")
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = MATH / "euler_vs_fea.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


def fig_scaling():
    E = np.linspace(4, 22, 50)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    t90 = a8["torque_n_mm"]["90"]
    ax.plot(E, t90 * E / 19.3, color="#1f5fa8", label="A8 with collars s2.75: torque at 90° (N·mm)")
    cap = fea[("B5_t200_a45", "deep", 0.0)]["capacity_T"]
    ax.plot(E, cap * E / 12 / 10, color="#c2571a", label="B5 t2.0 deep: tendon capacity at 0° (N ÷ 10)")
    top = ax.get_ylim()[1]
    for e, lab in ((5.3, "5.3 printed (Bambu)"), (12, "12 working"), (19.3, "19.3 bulk (Jabil)")):
        ax.axvline(e, color="grey", lw=0.7, ls=":")
        ax.text(e + 0.2, 0.55 * top, lab, fontsize=7, rotation=90, color="#5b6472")
    ax.set(xlabel="Young's modulus E (MPa)", ylabel="value", title="Every force and torque is a straight line through zero in E (section 1)")
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = MATH / "e_scaling.png"
    fig.savefig(p, dpi=170)
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------
def story():
    s = []
    s += [P("BARNES UI — the mathematics behind the analyses", "title"),
          P("Every formula used to size, simulate and choose the Type A and Type B finger joints; where each one "
            "lives in the code; a worked example with this project's own numbers; and the decision it feeds. "
            "Companion to " + link("docs/report/BARNES_print_decision_report.pdf", "BARNES_print_decision_report.pdf") + ".", "sub"),
          Spacer(1, 8)]

    s += [h1("0. How to read this")]
    s += bullets([
        "Each section answers one question (how stiff, how far, how much tendon force, when does it buckle, which one wins). "
        "It gives the equations, then a <b>worked example</b> with real inputs, then <b>where in the code</b> it is, then what "
        "decision it feeds.",
        "The order is the order you would use them on a new design: material first, then hand models (beams, tendon, "
        "buckling) to screen ideas in minutes, then FEA for the few that survive, then the selection rules.",
        "Units throughout: mm, N, MPa (= N/mm²), N·mm for moments and torques, radians inside formulas, degrees in tables.",
        "Symbols are collected in the appendix.",
    ])

    # 1 -------------------------------------------------------------------
    s += [h1("1. Material, strain and the E-scaling rule")]
    s += [h2("1.1 The TPU model: Neo-Hookean")]
    s += [P("TPU is rubbery: it stretches tens of per cent and stays elastic, so a linear Hooke's-law model is wrong at the strains "
            "here. The simplest model that handles large stretch is Neo-Hookean. It has one stiffness constant C<sub>10</sub> plus a "
            "bulk term that keeps the volume almost constant:")]
    s += eq(r"W = C_{10}\,(\bar I_1 - 3) + \frac{1}{D_1}\,(J-1)^2,\qquad \bar I_1 = J^{-2/3}\,\mathrm{tr}(F^{T}F),\quad J=\det F")
    s += [P("F is the deformation gradient (how each little cube of material is stretched and turned). The constants come from "
            "the small-strain Young's modulus E and Poisson's ratio ν:")]
    s += eq(r"\mu_0 = 2C_{10} = \frac{E}{2(1+\nu)},\qquad K = \frac{E}{3(1-2\nu)},\qquad D_1 = \frac{2}{K}")
    s += [P("With E = 12 MPa and ν = 0.4995 (nearly incompressible): μ<sub>0</sub> = 4.0027 MPa, C<sub>10</sub> = 2.0013 MPa. In a "
            "uniaxial pull with stretch λ = 1 + ε the engineering stress is")]
    s += eq(r"\sigma_{eng} = 2C_{10}\,(\lambda - \lambda^{-2})")
    s += [P("which is E·ε for small ε and softens gently above about 20 %. " + code("src/barnes_ui/core/material/models.py"))]

    s += [h2("1.2 Why every force and torque scales exactly with E")]
    s += [P("Every stress term in W is proportional to E (C<sub>10</sub> ∝ E and 1/D<sub>1</sub> ∝ E at fixed ν). Write the stress "
            "as σ = E·f(F). Equilibrium with no body force is ∇·σ = 0.")]
    s += bullets([
        "<b>Displacement control</b> (a joint bent to an angle): the boundary fixes the motion, so F is the same field for any E "
        "(the E cancels out of ∇·(E f(F)) = 0). Strains, shapes, range of motion and centre drift do not depend on E. Every "
        "reaction (moment, torque, stiffness, stress) is E × something fixed.",
        "<b>Force control</b> (round-2 tendon load T): ∇·(E f(F)) = 0 with traction T on the boundary is the same problem as "
        "∇·f(F) = 0 with traction T/E. So the deformation depends only on T/E, and a capacity found at 12 MPa is T<sub>cap</sub>(E) = "
        "T<sub>cap</sub>(12) · E/12. Contact keeps this true only if the penalty stiffness is also ∝ E, which is why it is set to "
        "10·E/h (section 5.5).",
    ])
    s += eq(r"X(E) = X(E_{run})\cdot\frac{E}{E_{run}}\qquad\mathrm{for\ any\ force,\ torque,\ stiffness,\ stress,\ capacity}")
    s += [P("Different studies were run at different E (A3 and Type B at 12, A6 at 13, A8 at 19.3 MPa), so they were all brought "
            "to one basis with this formula. SUNLU publishes no modulus, so the working value is 12 MPa, bracketed by 5.3 MPa "
            "(printed TPU 90A, Bambu datasheet, XY) and 19.3 MPa (bulk TPU 90A, Jabil). " + code("scripts/sunlu_rescale.py"))]
    t90 = a8["torque_n_mm"]["90"]
    cap = fea[("B5_t200_a45", "deep", 0.0)]["capacity_T"]
    s += example("rescaling two headline numbers", [
        f"A8 with collars, sagitta 2.75, was run at 19.3 MPa: torque at 90° = {t90:.3f} N·mm.",
        f"At 12 MPa: {t90:.3f} × 12 / 19.3 = <b>{t90 * 12 / 19.3:.2f} N·mm</b>. At 5.3 MPa: {t90 * 5.3 / 19.3:.2f} N·mm.",
        f"B5 t2.0 deep tendon capacity at 0° was found at 12 MPa: {cap:.1f} N. At 5.3 MPa: <b>{cap * 5.3 / 12:.1f} N</b>; at 19.3 MPa: {cap * 19.3 / 12:.1f} N.",
        "When your tensile test gives a real E, set E_SUNLU_MPA in scripts/sunlu_rescale.py and every number updates. "
        "Nothing needs to be re-simulated.",
    ])
    s += figure(fig_scaling(), "Figure 1. The E-scaling rule applied to two results. The bracket is the real uncertainty until the specimens are tested.", max_h=62 * mm)

    s += [h2("1.3 Which strain, and the 20 % limit")]
    s += [P("The solver (CalculiX, large-deformation mode NLGEOM) reports the Green–Lagrange strain tensor. It is turned into "
            "the largest principal <i>engineering</i> strain, the number a tensile test gives:")]
    s += eq(r"\mathbf{E}_{GL} = \frac{1}{2}\,(F^TF - I),\qquad \lambda_{max} = \sqrt{1 + 2\,e_{max}(\mathbf{E}_{GL})},\qquad \varepsilon = \lambda_{max} - 1")
    s += [P("e<sub>max</sub> is the largest eigenvalue. A 0.4 mm band at each collar root is left out of the peak: the sharp "
            "inside corner there is a mathematical singularity whose value keeps rising as the mesh is refined, so it does not "
            "converge to a real number. A real print has a small radius there. That is why a fillet is recommended wherever a "
            "strip meets a collar. The 20 % limit is a placeholder for fatigue (10 % and 30 % are drawn for reference) until the "
            "printed filament has been cycled. " + code("scripts/a8_meander_study.py", "TYPE B/analysis/fea_typeb.py"))]

    # 2 -------------------------------------------------------------------
    s += [PageBreak(), h1("2. Beam models: the minutes-long screening tools")]
    s += [h2("2.1 Bending strain, and why thickness is the strain knob")]
    s += [P("A strip of thickness t bent from curvature κ<sub>0</sub> to κ has surface strain")]
    s += eq(r"\varepsilon = \frac{t}{2}\,|\kappa - \kappa_0|\qquad\mathrm{(wrapping\ flat\ around\ a\ radius\ }R\mathrm{:}\ \varepsilon \approx \frac{t}{2R})")
    s += [P("and bending stiffness EI with I = w t³/12 for a rectangle of width w. So torque grows with t³ but strain with t: "
            "doubling thickness buys 8× the torque at 2× the strain. Width scales torque linearly and leaves strain alone, as "
            "long as the strip does not start bending sideways (which is what happened to wide A8 strips). This is the main "
            "sizing rule for every spring here: <b>choose t from the strain limit, then w for the torque</b>.")]

    s += [h2("2.2 The planar elastica (A6 sliding leaf)")]
    s += [P("A leaf that bends through large angles but does not stretch. Along arc length s, with tangent angle θ(s), internal "
            "moment M(s) and a constant internal force (n<sub>y</sub>, n<sub>z</sub>):")]
    s += eq(r"\frac{dy}{ds}=\cos\theta,\quad \frac{dz}{ds}=\sin\theta,\quad \frac{d\theta}{ds}=\kappa_0+\frac{M}{EI},\quad \frac{dM}{ds}=-(n_z\cos\theta - n_y\sin\theta)")
    s += [P("It is solved by <i>shooting</i>: guess the anchor moment M<sub>0</sub>, the force components and the free length, "
            "integrate (RK4, 400 steps), and adjust the guesses (least squares) until the far end (1, 2) lands in the guide mouth, "
            "(3) points along the guide, and (4) carries no force along the guide, since a frictionless slot cannot push along "
            "itself. Condition 4 is what makes the end <i>slide</i>. When the T-head hits its stop, the free length is fixed "
            "instead and condition 4 is dropped. Each angle starts from the previous solution (continuation). With EI = 1 the "
            "shape does not depend on stiffness at all, so EI is applied afterwards.")]
    s += [P("Torque comes from energy, which avoids sign mistakes:")]
    s += eq(r"U(\phi) = \int_0^{L}\frac{M^2}{2EI}\,ds,\qquad \tau(\phi) = \frac{dU}{d\phi},\qquad \bar\tau = \frac{U(\phi_{max})}{\phi_{max}}")
    s += [P("φ is the joint angle. The figure of merit for a return spring is the mean torque τ̄ over 0–105°, taken at the "
            "<i>worst</i> of four assumed axis positions, because the real PIP axis relative to the cuffs is not known. Pass "
            "rules: reaches 105°, restoring (τ &gt; 0) at every angle, at least 3.5 mm from the axis, peak strain ≤ 20 %. "
            + code("scripts/a6_rom_check.py", "scripts/a6_parameter_sweep.py"))]

    s += [h2("2.3 The extensible elastica (A3 twin strap) and why A3 cannot work as laid out")]
    s += [P("A3's straps are clamped at both ends and the distal clamp swings around the joint axis, so the distance between the "
            "ends changes. The arch has only arc − chord = 28.38 − 27.80 = 0.58 mm of slack. Beyond a few degrees the strap must "
            "<i>stretch</i>. Add axial strain N/EA to the elastica:")]
    s += eq(r"\frac{dy}{ds_0}=\Lambda\cos\theta,\quad \frac{dz}{ds_0}=\Lambda\sin\theta,\quad \Lambda = 1+\frac{n_y\cos\theta+n_z\sin\theta}{EA},\qquad \frac{EA}{EI}=\frac{12}{t^2}")
    s += [P("For t = 1 mm, EA/EI = 12 mm⁻²: stretching is 12× stiffer than bending per unit, so a strap forced to stretch becomes "
            "very stiff and very strained. That is why the sweep of 480 A3 variants found none that passes. A sliding end (A6) "
            "or a meander (A8) removes the stretch. " + code("scripts/a3_parameter_sweep.py"))]

    s += [h2("2.4 Linear curved beam (Castigliano), and its check against FEA")]
    s += [P("For a quick stiffness at 0°: treat each strap as a curved beam clamped at both ends (3 unknown end actions in plane), "
            "release one end and build the flexibility matrix from unit loads:")]
    s += eq(r"C_{ij} = \int\left(\frac{m_i m_j}{EI} + \frac{n_i n_j}{EA} + \frac{k\,v_i v_j}{GA}\right)ds,\qquad \mathbf{x} = C^{-1}\mathbf{d}")
    s += [P("d is the end displacement imposed by rotating the distal clamp about the joint axis; x are the end forces and moment; "
            "the restoring moment is their moment about the axis. The 3D version for meanders adds torsion (GJ) and the second "
            "bending axis, a 6×6 matrix, because a meander's runs parallel to the axis <i>twist</i> rather than bend.")]
    s += example("how sensitive a beam model is to its inputs (A3)", [
        "FEA joint stiffness of A3 1.0 mm: 6.103 N·mm/rad (mesh-converged to 0.94 %).",
        "Beam model at the FEA's own axis and clamp line: 8.96 % to 20.2 % stiffer, depending on where exactly the strap is taken to be clamped.",
        "Moving the assumed axis 2 mm (bounding-box centre z = 7.42 instead of the mounting features' z = 5.44) changes the beam result from 6.86 to 3.16 N·mm/rad.",
        "<b>Lesson:</b> the joint axis and the clamp line matter more than the beam theory. Always state both.",
    ])
    s += [P(code("src/barnes_ui/core/mechanics/curved_beam.py", "src/barnes_ui/core/mechanics/spatial_beam.py", "scripts/a3_rom_vs_fea.py"))]

    # 3 -------------------------------------------------------------------
    s += [PageBreak(), h1("3. Tendon mechanics: how much pull a joint needs")]
    s += [h2("3.1 What the servo can give")]
    s += eq(r"T_{avail} = \frac{\eta\,\tau_{stall}}{r_{horn}} = \frac{0.5\times 0.94\ \mathrm{N\,m}}{0.010\ \mathrm{m}} = 47\ \mathrm{N},\qquad \mathrm{stroke} = r_{horn}\,\phi_{servo} = 10\pi = 31.4\ \mathrm{mm}")
    s += [P("η = 0.5 derates the MG995 to half stall (it overheats at stall). The tendon is shared by MCP, PIP and DIP, so the "
            "three joints share one tension and their excursions add up against one stroke.")]

    s += [h2("3.2 The lever, from virtual work")]
    s += [P("The cleanest definition of the tendon's moment arm: if the joint closes by dθ, the tendon path shortens by dl, and the "
            "work T·dl equals the joint's work M·dθ. So")]
    s += eq(r"r(\theta) = -\frac{dl}{d\theta},\qquad M_{tendon} = T\,r(\theta)")
    s += [P("This works for any joint (pin, bending, rolling) as long as you can write the tendon length l(θ). It also says that "
            "lever and stroke are the same thing: a longer lever costs proportionally more tendon travel.")]
    s += [P("<b>Pin joint</b> (Type A; also used for fixed-centre Type B). Guide at (−a, h) on the proximal link, anchor at (x, h) on "
            "the distal link rotated by θ, with b = (x cos θ − h sin θ, x sin θ + h cos θ):")]
    s += eq(r"l = \|\mathbf{b} - (-a, h)\|,\qquad r = \frac{b_x h + b_y a}{l}")
    s += [P("<b>Bending joint</b> (B3, B6, B1 full notch, lattice: roughly constant curvature over the flex length L). The tendon at "
            "offset d runs as the chord of the inner arc of radius L/θ − d:")]
    s += eq(r"l(\theta) = 2\left(\frac{L}{\theta} - d\right)\sin\frac{\theta}{2},\qquad r = -\frac{dl}{d\theta}\ \mathrm{(numerically)}")
    s += [P("<b>Rolling joint</b> (B4). The contact point moves palmar by R sin(θ/2) as the lobes roll, eating into the lever:")]
    s += eq(r"r(\theta) \approx d - R\,\sin\frac{\theta}{2}")
    s += [P("This is why B4's roll radius was kept small: with the as-built d = 1.93 mm and a large R the lever goes negative "
            "part-way through flexion and the tendon would start <i>straightening</i> the joint. R was set so r ≥ 0.3 mm at the "
            "target flexion. " + code("scripts/tendon_routing_analysis.py", "scripts/tendon_pivot_optimizer.py", "TYPE B/round2/predict_round2.py"))]
    s += figure(fig_levers(), "Figure 2. Lever against flexion for the joint models at the PIP (flex zone 7.55 mm), up to 85° (the collars meet at about 76°). A fixed centre gains lever as it closes; rolling loses it.", max_h=70 * mm)

    s += [h2("3.3 Tension to hold a load")]
    s += [P("On the single-joint rig, a weight W hangs from a hook L<sub>hook</sub> = 44.8 mm from the PIP, with the distal arm "
            "raised θ above horizontal. Moment balance about the joint, including the joint's own spring k:")]
    s += eq(r"T = \frac{W\,L_{hook}\cos\theta + k\,\theta}{r(\theta)}")
    s += [P("For the whole finger, a fingertip force F normal to the distal phalanx loads joint j by the lengths of all links "
            "beyond it, projected (φ<sub>i</sub> is the cumulative angle of link i):")]
    s += eq(r"\tau_j = F\sum_{i\geq j} L_i\cos(\phi_{tip} - \phi_i)")
    s += example("why the deep tendon offset matters", [
        "At 0° the lever equals the offset d. Tension per newton on the hook: 44.8 / 1.93 = <b>23.2 N/N</b> as built; 44.8 / 3.40 = <b>13.2 N/N</b> with the deep tendon.",
        "So the same 1 N at the fingertip squeezes the joint with 23 N (as built) or 13 N (deep). Halving the squeeze for the same grip "
        "is the whole case for the deep-offset phalanges.",
        f"B5 t2.0 deep holds {cap:.1f} N of tension at 0° (FEA) → {cap:.1f} / 13.2 = <b>{cap / 13.2:.2f} N</b> on the hook at 12 MPa.",
    ])
    s += [h2("3.4 Choosing tendon guide positions (Type A)")]
    s += [P("For every combination of guide station a, anchor station x and offset h, the margin is the worst ratio of available "
            "to required torque over the grasp poses:")]
    s += eq(r"\mathrm{margin}(a,x,h) = \min_{\theta\in\mathrm{grasp}}\ \frac{T_{avail}\,r(\theta;a,x,h)}{k\,\theta + \tau_{load}(\theta)},\qquad \mathrm{excursion} = l(0) - l(\theta_{max})")
    s += [P("Keep only the Pareto front (more margin needs more excursion), then pick one point per joint to maximise the "
            "weakest joint's margin with the summed excursion ≤ 31.4 mm. Designs with lever &lt; 0.5 mm anywhere, or guides closer "
            "than 3.5 mm, are rejected.")]

    # 4 -------------------------------------------------------------------
    s += [PageBreak(), h1("4. Compression capacity: hand estimates")]
    s += [P("The tendon that bends a pinless joint also squeezes it along its length. In Type A the pin takes that load. In Type B "
            "the TPU does, and it fails in one of three ways, each with its own hand formula. These were the predictions; the "
            "round-2 FEA (section 5.6) then checked them.")]
    s += [h2("4.1 Thin leaves and strips: Euler buckling")]
    s += [P("A leaf held square at both ends (collars) buckles at")]
    s += eq(r"P_{cr} = \frac{4\pi^2 E I}{L^2},\qquad I = \frac{w t^3}{12}")
    s += [P("For n leaves in parallel multiply by n. A B5 crossed strip of length L<sub>s</sub> at ±α/2 to the axis carries the "
            "axial load at an angle, adding a cos(α/2) factor; B5 has 4 lanes. B1's notch is two webs of notch length L<sub>n</sub>.")]
    e3, e5 = euler_b3(), euler_b5()
    s += example("B3_t200_w30 and B5_t200_a45 at the PIP, E = 12 MPa", [
        f"B3: n = {e3['n']}, t = {e3['t']}, w = {e3['w']}, L = {e3['L']} mm → I = {e3['w']}×{e3['t']}³/12 = {e3['I']:.2f} mm⁴; "
        f"P = {e3['n']}×4π²×12×{e3['I']:.2f}/{e3['L']}² = <b>{e3['P']:.1f} N</b>.",
        f"B5: 4 lanes, t = {e5['t']}, w = {e5['w']}, L<sub>s</sub> = {e5['Ls']} mm, α = {e5['a']:.0f}° → I = {e5['I']:.2f} mm⁴, cos(α/2) = {e5['c']:.3f}; "
        f"P = 4×{e5['c']:.3f}×4π²×12×{e5['I']:.2f}/{e5['Ls']}² = <b>{e5['P']:.1f} N</b>.",
        f"FEA: B3 buckled sideways at <b>{fea[('B3_t200_w30', 'as-built', 0.0)]['capacity_T']:.1f} N</b>, a third of Euler. "
        f"B5 deep reached <b>{cap:.1f} N</b> (strain-limited), close to its {e5['P']:.1f} N estimate.",
        "<b>Lesson:</b> Euler assumes perfectly straight, centrally loaded leaves. The tendon pushes off-centre and the 1 % side "
        "push finds the sideways mode, so a plain leaf buckles far earlier. A crossed strip is braced against that mode and "
        "behaves much closer to the formula.",
    ])
    s += figure(fig_euler(), "Figure 3. Euler's formula against the FEA for the B3 dual leaf. Treat hand buckling loads for single leaves as upper bounds.", max_h=62 * mm)

    s += [h2("4.2 Stocky struts and knuckles: 20 % strain over an area")]
    s += eq(r"T_{cap} = 0.2\,E\,A,\qquad A_{strut} = \mathrm{neck\ area},\qquad A_{knuckle} = 2r\,w_{bearing}")
    b9, b8 = r2["B9_n150"], r2["B8_y00_r150"]
    s += example("B9_n150 and B8_y00_r150", [
        f"B9: neck area {b9['neck_area_mm2']} mm² → 0.2×12×{b9['neck_area_mm2']} = <b>{0.2 * 12 * float(b9['neck_area_mm2']):.1f} N</b>. "
        f"FEA at 0°: {fea[('B9_n150', 'as-built', 0.0)]['capacity_T']:.1f} N. Good agreement, but at 60° bending alone already strains the neck to 37 %.",
        f"B8: knuckle r = {b8['knuckle_r_mm']} mm, bearing width {b8['bearing_w_total']} mm → 0.2×12×2×{b8['knuckle_r_mm']}×{b8['bearing_w_total']} = "
        f"<b>{0.2 * 12 * 2 * float(b8['knuckle_r_mm']) * float(b8['bearing_w_total']):.1f} N</b>. FEA reached ≥ 5.8 N (a lower bound; the contact solution stopped first).",
    ])
    s += [h2("4.3 Rolling lobes: Hertz line contact")]
    s += [P("Two TPU cylinders of radius R pressed together over width w. The combined radius is R' = R/2 and the combined "
            "modulus for two identical materials E* = E / (2(1 − ν²)). Hertz gives the peak pressure p<sub>0</sub> for a load P; "
            "set p<sub>0</sub> = 0.2E (about 20 % local strain) and solve for P:")]
    s += eq(r"p_0 = \sqrt{\frac{P\,E^*}{\pi\,w\,R'}}\quad\Rightarrow\quad T_{cap} = \frac{\pi\,w\,R'\,p_0^{2}}{E^*}")
    Rd, wb = float(r2d["B4_t100_a60_deep"]["roll_r_mm"]), float(r2d["B4_t100_a60_deep"]["bearing_w_total"])
    es = E12 / (2 * (1 - 0.45 ** 2))
    s += example("B4_t100_a60_deep", [
        f"R = {Rd:.3f} mm → R' = {Rd / 2:.3f} mm; w = {wb} mm; ν = 0.45 → E* = 12/(2×(1−0.45²)) = {es:.2f} MPa; p<sub>0</sub> = 2.4 MPa.",
        f"T<sub>cap</sub> = π×{wb}×{Rd / 2:.3f}×2.4²/{es:.2f} = <b>{math.pi * wb * Rd / 2 * 2.4 ** 2 / es:.1f} N</b>. FEA reached ≥ 11.1 N at 12 % strain before the contact solution stopped.",
    ])
    s += [h2("4.4 From capacity to fingertip, and the collar hard stop")]
    s += eq(r"W_{hook,max} = \frac{T_{cap}}{\max_\theta\,(L_{hook}\cos\theta / r(\theta))},\qquad \theta_{collar} = 2\arctan\frac{F_{flex}/2}{h_c + y_{pivot}}")
    s += [P(f"For the PIP the collars (half-height h<sub>c</sub> = 5.7 mm, flex zone F = 7.55 mm) meet at 2·atan(3.775/5.7) = "
            f"{math.degrees(2 * math.atan(3.775 / 5.7)):.0f}° about a central pivot. The round-1 FEA found about 76° (conservative "
            "estimate). This, not the flexure, sets most Type B ranges; palmar chamfers on the collars would lift it.")]

    # 5 -------------------------------------------------------------------
    s += [PageBreak(), h1("5. The finite-element method as used here")]
    s += [h2("5.1 Mesh and solver")]
    s += bullets([
        "Solver: CalculiX (versions 2.21 and 2.23 agreed to 5 significant figures on B3_t200_w30), direct solver SPOOLES, "
        "geometric nonlinearity on (NLGEOM), Newton–Raphson with automatic increments.",
        "Elements: 10-node quadratic tetrahedra (C3D10) from gmsh. Rule: at least 2 elements through the thinnest feature, "
        "element size h = min(t, w)/2, floor 0.2 mm. Round-2 joints use a <i>graded</i> mesh (fine in the thin spring lane, "
        "0.5 mm in bulky bearings, 0.8 mm in collars) to keep memory under 8 GB.",
    ])
    s += [h2("5.2 Boundary conditions: the part that decides whether the answer is right")]
    s += bullets([
        "Proximal collar: every node fixed. Distal collar: <b>every</b> surface inside the attachment tied to one rigid reference "
        "node. (Tying only one face made A3 63× too soft.)",
        "<b>Type A</b> (spring beside a pin): the reference node sits on the pin axis, its translations are fixed and it is rotated. "
        "(Leaving translations free made A3 55× too soft, with no warning.) The axis position must be given explicitly.",
        "<b>Type B</b> (the TPU is the joint): rotation prescribed, translations <b>free</b>. That is a pure moment under "
        "displacement control, and the joint finds its own centre of rotation, which is reported as axis drift.",
        "Joint angle is applied in increments up to the target (A8 to 100°, Type B PIP to 105°); each increment records the "
        "reaction moment, so the output is a torque–angle curve.",
    ])
    s += [h2("5.3 What is extracted from a torque–angle curve")]
    s += eq(r"k_0 = \mathrm{slope\ of\ a\ line\ fit\ of\ }M(\phi)\ \mathrm{for}\ \phi\leq 3^\circ,\qquad U_{0\to90} = \int_0^{\pi/2} M\,d\phi,\qquad \mathrm{linearity} = \frac{M_{90}}{k_0\,\pi/2}")
    s += example("A8 with collars, sagitta 2.75 (E = 19.3 MPa)", [
        f"k<sub>0</sub> = {a8['k0_n_mm_per_rad']:.3f} N·mm/rad; M<sub>90</sub> = {t90:.3f} N·mm; linearity = {t90:.3f} / ({a8['k0_n_mm_per_rad']:.3f} × 1.571) = "
        f"<b>{t90 / (a8['k0_n_mm_per_rad'] * math.pi / 2):.2f}</b>. Above 1 means the spring stiffens as it closes, which is useful because the "
        "finger needs the most return help when most flexed.",
        f"Without collars (rigid ends) the same strip gave {a8base['torque_n_mm']['90']:.2f} N·mm: flexible collars cost "
        f"{100 * (1 - t90 / a8base['torque_n_mm']['90']):.0f} %.",
    ])
    s += [h2("5.4 Off-axis stiffness (round 1)")]
    s += [P("Three small linear load cases on the same mesh give lateral, torsional and axial stiffness, which convert to "
            "what a user would notice:")]
    s += eq(r"\delta_{side} = \frac{1\,\mathrm{N}\times L_{tip}}{k_{lat}},\qquad \phi_{twist} = \frac{1\,\mathrm{N}\times 5\,\mathrm{mm}}{k_{tor}},\qquad \Delta_{axial} = \frac{T_{end}}{k_{ax}}")
    s += [h2("5.5 Contact")]
    s += [P("Where two surfaces may touch (A8 strip on the bone, B4 lobes, B8 knuckle in cup) a surface-to-surface penalty "
            "contact is used, with penalty stiffness ∝ E so the E-scaling rule still holds:")]
    s += eq(r"k_{penalty} = 10\,\frac{E}{h}")
    s += [P("h is the local element size. The bone surface is sampled and searched with a KD-tree to find the A8 clearance "
            "(smallest distance from the strip's underside to the phalanx), which set the sagitta trade-off: 2.75 mm keeps 0.39 mm "
            "clearance; 3.00 mm keeps 0.60 mm.")]
    s += [h2("5.6 Round-2 tendon-load protocol and how a capacity is read")]
    s += bullets([
        "<b>Step 1, bend:</b> rotate the distal body to the pose (0°, 30° or 60°), translations free.",
        "<b>Step 2, squeeze:</b> hold the rotation and ramp a force T (up to 150 N) along the tendon's line, plus a 1 % sideways "
        "push so a symmetric joint has a buckling mode to find instead of sitting on a perfect bifurcation.",
        "Bearings (B4, B8) are run <b>guided</b>: the distal body is driven along the tendon line under displacement control "
        "(a free load let their thin return leaves buckle at about 0.3 N before the bearing seated). Their bend follows the "
        "bearing's own kinematics: rotation about the knuckle centre for B8; for B4 the distal lobe centre orbits the "
        "proximal one by θ/2 while the body turns by θ.",
    ])
    s += [P("The capacity is the first of three events:")]
    s += eq(r"T_{cap} = \min\left\{\ T_{limit\ point},\ \ T\,|_{\,k_t < 0.1\,k_{t,0}},\ \ T\,|_{\,\varepsilon_{max} = 20\%}\ \right\},\qquad k_t = \frac{\Delta T}{\Delta u_{along}}")
    s += [P("A limit point is where the solver can find no equilibrium at a higher load (buckling or collapse). k<sub>t</sub> is "
            "the axial tangent stiffness; k<sub>t,0</sub> is the median over the first 5 % of increments. If bending to the pose "
            "already exceeds 20 %, the capacity is 0 (the joint cannot reach that angle). A guided run that stops before any of "
            "these is reported as a <b>lower bound</b> (≥). " + code("TYPE B/round2/fea_round2.py"))]
    s += [h2("5.7 Mesh convergence")]
    s += [P("Run the same case at three element sizes and compare the quantity you will use:")]
    s += eq(r"\mathrm{spread} = \frac{\max_h X_h - \min_h X_h}{X_{h_{ref}}}")
    if len(a8conv) == 2:
        x5, x3 = a8conv["0.5"]["torque_n_mm"]["90"], a8conv["0.3"]["torque_n_mm"]["90"]
        x4 = a8base["torque_n_mm"]["90"]
        s += example("A8 strip, torque at 90°", [
            f"h = 0.5 / 0.4 / 0.3 mm → {x5:.3f} / {x4:.3f} / {x3:.3f} N·mm → spread = ({max(x5, x4, x3):.3f} − {min(x5, x4, x3):.3f}) / {x4:.3f} = "
            f"<b>{100 * (max(x5, x4, x3) - min(x5, x4, x3)) / x4:.2f} %</b>. Converged; 0.4 mm is fine.",
            "Peak strain moves more (15.6 / 16.5 / 16.1 %) because it is a local maximum, not an integral. Judge strain against "
            "the limit with about ±1 point of mesh uncertainty.",
        ])

    # 6 -------------------------------------------------------------------
    s += [PageBreak(), h1("6. Turning results into a choice")]
    s += [h2("6.1 Gates: pass or fail before any ranking")]
    s += [table([
        ["Gate", "Formula", "Threshold", "Why"],
        ["Strain", "peak principal engineering strain over the usable range", "≤ 20 %", "fatigue life of TPU (placeholder)"],
        ["Return", "margin = M(20°) / M<sub>gravity</sub>", "≥ 1", "no extensor: the spring must lift the distal finger's own weight"],
        ["Range", "first of collision, 20 % strain, self-contact, solver stop", "near the joint's target", "the joint must close"],
        ["Tendon squeeze (Type B)", "T<sub>cap</sub> vs T needed for the grip", "T<sub>cap</sub> above it", "otherwise it buckles before gripping"],
        ["Fit (Type A)", "clearance to the bone, axis distance", "&gt; 0.25 mm; ≥ 3.5 mm", "it must not rub or cut through the joint"],
    ], widths=[26 * mm, 62 * mm, 32 * mm, W - 120 * mm])]
    s += eq(r"M_{gravity} = \sum_i m_i\,g\,x_i\qquad (\mathrm{distal\ chain\ horizontal:\ MCP\ 3.68,\ PIP\ 0.80,\ DIP\ 0.15\ N\,mm})")
    s += [h2("6.2 Ranking within a family (round 1)")]
    s += [P("Each criterion is normalised so the family's best = 1 and worst = 0, with a minimum spread so tiny differences count "
            "as ties (3° of range, 2 points of strain, 0.3 N, 1°, 1°, 0.2 mm, 0.03 mm), then combined with weights:")]
    s += eq(r"s_c(v) = \max\!\left(0,\ 1 - \frac{|x_{best} - x_v|}{\max(|x_{best}-x_{worst}|,\ \mathrm{floor}_c)}\right),\qquad S(v) = \sum_c w_c\,s_c(v)")
    s += [P("Balanced weights: range 0.30, strain 0.25, tendon force 0.15, sideways 0.10, drift 0.10, twist 0.05, compression 0.05. "
            "The winner was re-checked under three other weightings (range-first, durability-first, equal). A choice that holds "
            "under all four does not depend on the weights. " + code("TYPE B/analysis/analyse_results.py"))]
    s += [h2("6.3 How the print list followed from the numbers")]
    s += bullets([
        f"<b>A8 with collars</b>: the strongest Type A spring inside 20 % strain on the real PIP; torque converged; with collars "
        f"{t90 * 12 / 19.3:.2f} N·mm at 90° at 12 MPa. Sagitta 3.00 kept as well: 0.60 mm clearance and 19.9 % junction strain for 2.5 % less torque.",
        "<b>A6</b>: passes all four axis positions by the elastica; R28/1.4 has 3.2 points of strain margin, R32/1.8 sits at 19.8 %, so R28 is printed first.",
        f"<b>B5 t2.0 deep</b>: the only Type B joint whose resolved capacity ({cap:.1f} N at 0°, 10.3 N at 60°) clears the grip loads by a useful margin.",
        "<b>B4, B8</b>: the bearing route is the only way past the flexure-buckling limit; the FEA could give only lower bounds, so the "
        "print is the test.",
        "<b>Set aside</b>: B1, B9 (strain-limited just bending to 60°), B6 and the lattice (failed earlier gates), B3 (buckles at 10 N).",
    ])

    # 7 -------------------------------------------------------------------
    s += [h1("7. Geometry operations used along the way")]
    s += [h2("7.1 Fitting one frame onto another (Kabsch)")]
    s += [P("To place the A3 collars on the A8 strip, the same strip vertices were found in both frames and the best rotation R and "
            "translation t computed:")]
    s += eq(r"H = \sum_i (p_i-\bar p)(q_i-\bar q)^T = U\Sigma V^T,\qquad R = V\,\mathrm{diag}(1,1,\det VU^T)\,U^T,\qquad t = \bar q - R\bar p")
    s += [P("Residual 4.6 × 10⁻¹² mm: an exact fit. " + code("scripts/a8_collared_geometry.py"))]
    s += [h2("7.2 Instantaneous centre of rotation")]
    s += [P("For a body point P moving with velocity v at unit rotation rate, the centre is c = P + (−v<sub>y</sub>, v<sub>x</sub>). "
            "For a constant-curvature joint P(θ) = (L/θ · sin θ, L/θ · (1 − cos θ)), differentiated numerically. Its drift from mid "
            "flex zone is a ranking criterion because a wandering centre changes the tendon lever.")]

    # 8 -------------------------------------------------------------------
    s += [PageBreak(), h1("8. Recreating the work yourself")]
    s += [P("Order of operations for a new joint idea, from minutes to hours:")]
    s += [table([
        ["Step", "What", "Tool / command", "Time"],
        ["1", "Strain-size the spring: t from ε = tΔκ/2 ≤ 0.2, then w for torque", "by hand (section 2.1)", "minutes"],
        ["2", "Tendon lever and tension per newton at 0°, 30°, 60°", "python \"TYPE B/round2/predict_round2.py\"", "seconds"],
        ["3", "Compression capacity by hand (Euler / strain / Hertz)", "same script", "seconds"],
        ["4", "Large-deflection beam if it bends a lot (elastica)", "python scripts/a6_rom_check.py", "minutes"],
        ["5", "Bending FEA: torque–angle, strain, range, return margin", "python \"TYPE B/analysis/fea_typeb.py\" &lt;variant&gt; PIP", "2–80 min"],
        ["6", "Tendon-load FEA at 0/30/60°", "python \"TYPE B/round2/fea_round2.py\" &lt;variant&gt; --angle 60", "0.5–2 h"],
        ["7", "Type A spring on the real bone, with contact", "python scripts/a8_meander_study.py --groups ...", "~2 h per case"],
        ["8", "Mesh check on the chosen design (3 sizes)", "--printable-element-size 0.5 / 0.4 / 0.3", "hours"],
        ["9", "Put everything on one E and rank", "python scripts/sunlu_rescale.py; python \"TYPE B/analysis/analyse_results.py\" PIP", "seconds"],
        ["10", "Rebuild the reports", "python scripts/build_print_report.py; python scripts/build_math_report.py", "a minute"],
    ], widths=[10 * mm, 66 * mm, 78 * mm, W - 154 * mm])]
    s += [Spacer(1, 6), h2("8.1 Mistakes that produce plausible but wrong numbers (all happened here)")]
    s += bullets([
        "Joint axis at the bounding-box centre instead of the real joint: A3 stiffness halved. Always give the axis explicitly.",
        "Tying one face of a collar instead of all of it: 63× too soft. Leaving a pinned joint's translations free: 55× too soft.",
        "Measuring a section with a cut that is not perpendicular to the member: 5 % too thick at 17°, so 16 % too stiff.",
        "Clamping a beam model 0.5 mm shorter than the FEA: most of a reported 24 % disagreement.",
        "Trusting Euler for a single leaf: 3× too optimistic (section 4.1).",
        "Reporting a solver stop as 'capacity 0': it means 'not resolved', not 'no strength'. Say which.",
        "Comparing torques from studies at different E without rescaling (section 1.2).",
    ])
    s += [h2("8.2 When the specimens are tested")]
    s += bullets([
        "Tensile 1BA bars: E = slope of stress against strain from 0.5 % to 2 %, mean of at least 3 per thickness. Set E_SUNLU_MPA.",
        "Ø10 × 10 compression cylinder: E in compression from 2–10 % strain. The B4/B8 bearings depend on this one.",
        "If the stress–strain curve bends noticeably before 20 %, fit Neo-Hookean (or two-term Mooney–Rivlin) with "
        "HyperelasticModel.fit_uniaxial and re-run the few chosen designs. Rankings will not change; absolute numbers will.",
        "Cycle a strip to find the real strain limit, and replace the 20 % everywhere it appears (STRAIN_LIMIT in the scripts).",
    ])

    # appendix ----------------------------------------------------------
    s += [h1("Appendix: symbols")]
    s += [table([
        ["Symbol", "Meaning", "Unit"],
        ["E, ν, μ<sub>0</sub>, C<sub>10</sub>", "Young's modulus, Poisson's ratio, initial shear modulus, Neo-Hookean constant", "MPa, –"],
        ["t, w, L, I", "thickness (through the bend), width, free length, second moment w t³/12", "mm, mm⁴"],
        ["κ, κ<sub>0</sub>, ε", "curvature, initial curvature, engineering strain", "1/mm, –"],
        ["θ, φ", "joint flexion angle", "rad (deg in tables)"],
        ["M, τ, k, k<sub>0</sub>", "moment / torque about the joint; joint stiffness; initial stiffness", "N·mm, N·mm/rad"],
        ["T, r, d", "tendon tension, tendon lever about the joint, tendon offset from the neutral axis", "N, mm"],
        ["L<sub>hook</sub>, W", "rig hook distance (44.8 mm), hook load", "mm, N"],
        ["P<sub>cr</sub>, T<sub>cap</sub>", "buckling load, compression capacity in tendon tension", "N"],
        ["R, R', E*", "roll radius, combined radius R/2, combined contact modulus", "mm, MPa"],
        ["h", "element size", "mm"],
    ], widths=[34 * mm, W - 64 * mm, 30 * mm])]
    return s


def build():
    MATH.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(PDF), pagesize=R.A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title="BARNES UI — mathematics of the analyses", author="BARNES UI")

    def foot(c, d):
        c.saveState()
        c.setFont("DV", 7.5)
        c.setFillColor(R.MUTED)
        c.drawString(15 * mm, 9 * mm, "BARNES UI — the mathematics behind the analyses")
        c.drawRightString(R.A4[0] - 15 * mm, 9 * mm, f"page {d.page}")
        c.restoreState()

    doc.build(story(), onFirstPage=foot, onLaterPages=foot)
    print(PDF)


if __name__ == "__main__":
    build()
