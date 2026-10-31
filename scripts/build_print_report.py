"""Build the print-decision report: every analysis so far, on one material basis,
with what to print next and why.

    python scripts/build_print_report.py

Reads only committed results, so it can be re-run whenever a result changes. Writes
docs/report/BARNES_print_decision_report.pdf and the figures it makes into
docs/report/figures/. Narrative text lives in docs/report/narrative.py, kept apart
from the plumbing so it can be edited without touching the layout.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,  # noqa: E402
                                SimpleDocTemplate, Spacer, Table, TableStyle)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "report"
FIG = OUT / "figures"
BRANCH = "claude/modest-cray-kbb75b"
GH = f"https://github.com/Melle2006/BARNES_UI/blob/{BRANCH}/"
GH_TREE = f"https://github.com/Melle2006/BARNES_UI/tree/{BRANCH}/"

spec = importlib.util.spec_from_file_location("narrative", OUT / "narrative.py")
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)

# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DVI", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))  # no oblique face installed; captions are set apart by colour
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DVI", boldItalic="DVB")
ss = getSampleStyleSheet()
INK, MUTED, ACCENT, RULE = (colors.HexColor(c) for c in ("#1d2430", "#5b6472", "#1f5fa8", "#d5dae1"))
S = dict(
    title=ParagraphStyle("t", parent=ss["Title"], fontName="DVB", fontSize=20, leading=25, textColor=INK, alignment=TA_LEFT),
    sub=ParagraphStyle("s", parent=ss["Normal"], fontName="DV", fontSize=10.5, leading=14, textColor=MUTED),
    h1=ParagraphStyle("h1", parent=ss["Heading1"], fontName="DVB", fontSize=15, leading=19, textColor=INK, spaceBefore=6, spaceAfter=6),
    h2=ParagraphStyle("h2", parent=ss["Heading2"], fontName="DVB", fontSize=12, leading=15, textColor=ACCENT, spaceBefore=8, spaceAfter=4),
    body=ParagraphStyle("b", parent=ss["Normal"], fontName="DV", fontSize=9.2, leading=12.6, textColor=INK, spaceAfter=4),
    bullet=ParagraphStyle("bu", parent=ss["Normal"], fontName="DV", fontSize=9.2, leading=12.4, textColor=INK, leftIndent=11, bulletIndent=2, spaceAfter=2),
    cap=ParagraphStyle("c", parent=ss["Normal"], fontName="DVI", fontSize=8, leading=10, textColor=MUTED, spaceAfter=8),
    cell=ParagraphStyle("cell", parent=ss["Normal"], fontName="DV", fontSize=7.6, leading=9.4, textColor=INK),
    cellb=ParagraphStyle("cellb", parent=ss["Normal"], fontName="DVB", fontSize=7.6, leading=9.4, textColor=INK),
    link=ParagraphStyle("l", parent=ss["Normal"], fontName="DV", fontSize=7.6, leading=9.6, textColor=ACCENT),
)
W = A4[0] - 30 * mm


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def table(rows, widths=None, header=True, zebra=True):
    data = [[c if not isinstance(c, str) else Paragraph(c, S["cellb" if (header and i == 0) else "cell"])
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")))
    if zebra:
        for i in range(1 + header, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    t.setStyle(TableStyle(st))
    return t


def figure(path, caption, width=W, max_h=110 * mm):
    path = Path(path)
    if not path.exists():
        return [P(f"<i>[figure missing: {path.relative_to(REPO)}]</i>", "cap")]
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(str(path)).getSize()
    w = width
    h = w * ih / iw
    if h > max_h:
        h = max_h
        w = h * iw / ih
    return [KeepTogether([Image(str(path), width=w, height=h), P(caption, "cap")])]


def link(path, label=None, tree=False):
    url = (GH_TREE if tree else GH) + path.replace(" ", "%20")
    return f'<link href="{url}" color="#1f5fa8">{label or path}</link>'


def f1(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_round2():
    out = {}
    for p in sorted((REPO / "TYPE B/round2/fea/results").glob("*.json")):
        r = json.loads(p.read_text())
        key = r["variant"] + ("_deep" if r["offset"] == "deep" else "")
        out.setdefault(key, {})[r["angle"]] = r
    return out


def load_predictions():
    rows = list(csv.DictReader(open(REPO / "TYPE B/round2/predictions.csv")))
    return {r["variant"]: r for r in rows if r.get("joint", "PIP") == "PIP"}


def load_summary():
    return {r["variant"]: r for r in csv.DictReader(open(REPO / "TYPE B/analysis/results/summary_PIP.csv"))}


def load_a8_convergence():
    pts = []
    base = json.loads((REPO / "results/a8_index_pip_printable/cases/print_2T_w1.2_h2.4_s2.75.json").read_text())
    pts.append((0.4, base))
    for d in sorted((REPO / "results/a8_mesh_convergence").glob("h*")):
        f = d / "cases" / "print_2T_w1.2_h2.4_s2.75.json"
        if f.exists():
            r = json.loads(f.read_text())
            if "failure" not in r:
                pts.append((float(d.name[1:]), r))
    return sorted(pts, key=lambda x: -x[0])


# ---------------------------------------------------------------------------
# figures made here
# ---------------------------------------------------------------------------
def fig_round2(r2, preds, basis):
    FIG.mkdir(parents=True, exist_ok=True)
    names = [n for n in N.ROUND2_ORDER if n in r2]
    if not names:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), gridspec_kw=dict(width_ratios=[1.25, 1]))
    ax = axes[0]
    x = np.arange(len(names))
    angles = sorted({a for n in names for a in r2[n]})
    wbar = 0.8 / max(1, len(angles))
    palette = ["#1f5fa8", "#e07b39", "#3a9d5d"]
    for i, a in enumerate(angles):
        vals = [r2[n].get(a, {}).get("capacity_T") for n in names]
        lower = [bool(r2[n].get(a, {}).get("guided")) and "lower bound" in r2[n].get(a, {}).get("limited_by", "")
                 for n in names]
        bars = ax.bar(x + (i - (len(angles) - 1) / 2) * wbar, [v or 0 for v in vals], wbar * 0.92,
                      color=palette[i % 3], label=f"pose {a:g}°")
        for b, lb in zip(bars, lower):
            if lb:
                b.set_hatch("///")
                b.set_alpha(0.55)
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.8, "≥", ha="center", fontsize=8)
    est = []
    for n in names:
        p = preds.get(n) or preds.get(n.replace("_deep", ""))
        est.append(float(p["compression_capacity_N"]) if p and p.get("compression_capacity_N") else np.nan)
    top = 60.0
    est_c = [min(e, top - 2) if np.isfinite(e) else np.nan for e in est]
    ax.scatter(x, est_c, marker="_", s=420, color="#222", zorder=5, label="hand estimate (TEST_PLAN)")
    for xi, e in zip(x, est):
        if np.isfinite(e) and e > top - 2:
            ax.annotate(f"{e:.0f} ↑", (xi, top - 2), xytext=(0, -11), textcoords="offset points",
                        ha="center", fontsize=7)
    ax.set_ylim(0, top)
    ax.axhline(basis["servo_tension_N"], color="#b03030", lw=1, ls="--")
    ax.text(len(names) - 0.5, basis["servo_tension_N"] + 1.5, "servo tension 47 N", ha="right",
            fontsize=7.5, color="#b03030")
    ax.set_xticks(x, [n.replace("_", " ") for n in names], rotation=30, ha="right", fontsize=7.5)
    ax.set_ylabel("tendon tension the joint carries (N), E = 12 MPa")
    ax.set_title("Round 2: tendon capacity at the PIP (FEA)", fontsize=9.5)
    ax.legend(fontsize=7, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    for k, n in enumerate(names):
        for a, r in sorted(r2[n].items()):
            if a != 0.0 or not r.get("load"):
                continue
            T = [0] + [l["T"] for l in r["load"]]
            d = [0] + [l["du_along"] for l in r["load"]]
            line, = ax.plot(d, T, lw=1.3, label=n.replace("_", " "))
            cap = r.get("capacity_T")
            if cap:
                ax.plot(np.interp(cap, T, d), cap, "o", ms=4, color=line.get_color())
    ax.set_xlabel("joint shortening along the tendon (mm)")
    ax.set_ylabel("tendon tension (N)")
    ax.set_xlim(0, 2.0)
    ax.set_ylim(0, 45)
    ax.set_title("Load–shortening at 0° (dot = capacity)", fontsize=9.5)
    ax.legend(fontsize=6.5, frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG / "round2_capacity.png"
    fig.savefig(p, dpi=180)
    plt.close(fig)
    return p


def fig_return_gate(summary, basis):
    names = N.RETURN_GATE_NAMES
    lo, hi = basis["E_bracket_mpa"]
    fig, ax = plt.subplots(figsize=(8.5, 3.0))
    x = np.arange(len(names))
    m = np.array([float(summary[n]["return_margin"]) for n in names])
    ax.vlines(x, m * lo / 12, m * hi / 12, color="#9fb6d4", lw=6)
    ax.scatter(x, m, color="#1f5fa8", zorder=3, label="at 12 MPa")
    ax.axhline(1.0, color="#b03030", ls="--", lw=1)
    ax.text(len(names) - 0.6, 1.05, "holds the finger straight above this line", ha="right", fontsize=7, color="#b03030")
    ax.set_yscale("log")
    ax.set_xticks(x, [n.replace("_", " ") for n in names], rotation=30, ha="right", fontsize=7.5)
    ax.set_ylabel("return margin (×)")
    ax.set_title(f"Return gate across the modulus bracket {lo}–{hi} MPa (bar) — round-1 candidates", fontsize=9.5)
    ax.grid(axis="y", alpha=0.3, which="both")
    fig.tight_layout()
    p = FIG / "return_gate_bracket.png"
    fig.savefig(p, dpi=180)
    plt.close(fig)
    return p


def fig_a8_convergence(pts):
    if len(pts) < 2:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for h, r in pts:
        t = r["torque_n_mm"]
        angs = sorted(float(a) for a in t)
        ax.plot(angs, [t[f"{a:g}"] for a in angs], marker="o", ms=3, label=f"element {h} mm ({r['mesh']['elements']} el.)")
    ax.set_xlabel("PIP flexion (°)")
    ax.set_ylabel("restoring torque (N·mm), E = 19.3 MPa as run")
    ax.set_title("A8 selected strip: mesh convergence", fontsize=9.5)
    ax.legend(fontsize=7.5, frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG / "a8_mesh_convergence.png"
    fig.savefig(p, dpi=180)
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(15 * mm, 10 * mm, "BARNES UI — finger joint analysis and print decision")
    canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"page {doc.page}")
    canvas.restoreState()


def build():
    basis = json.loads((REPO / "results/sunlu_rescale/basis.json").read_text())
    r2, preds, summary = load_round2(), load_predictions(), load_summary()
    a8c = load_a8_convergence()
    f_r2 = fig_round2(r2, preds, basis)
    f_gate = fig_return_gate(summary, basis)
    f_a8c = fig_a8_convergence(a8c)
    ctx = dict(REPO=REPO, basis=basis, r2=r2, preds=preds, summary=summary, a8c=a8c,
               fig_round2=f_r2, fig_gate=f_gate, fig_a8c=f_a8c,
               P=P, bullets=bullets, table=table, figure=figure, link=link, f1=f1, W=W, mm=mm,
               Spacer=Spacer, PageBreak=PageBreak)
    story = N.story(ctx)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "BARNES_print_decision_report.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title="BARNES finger joints: analysis summary and print decision",
                            author="Claude Code")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(out)


if __name__ == "__main__":
    build()
